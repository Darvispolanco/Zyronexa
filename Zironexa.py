import os
import stripe
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import re
import json
import pandas as pd
from io import BytesIO

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_secreta_123")

# Config carpeta uploads
UPLOAD_FOLDER = 'static/comprobantes'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Config Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_ACCOUNT_ID = os.getenv("STRIPE_ACCOUNT_ID")

# Config
PROPIETARIO_TELEFONO = "84907210"
PASSWORD_PROPIETARIO = os.getenv("PASSWORD_PROPIETARIO", "123456")
TIPO_CAMBIO = 36
LIMITE_DIARIO_BAMPRO = 29000

PLANES = {
    1: {"nombre": "Plan Free", "precio": 500, "ganancia_diaria": 20, "porcentaje": 4.0},
    2: {"nombre": "Plan Básico", "precio": 1500, "ganancia_diaria": 67, "porcentaje": 4.5},
    3: {"nombre": "Plan Intermedio", "precio": 5000, "ganancia_diaria": 250, "porcentaje": 5.0},
    4: {"nombre": "Plan Avanzado", "precio": 10000, "ganancia_diaria": 550, "porcentaje": 5.5},
    5: {"nombre": "Plan Profesional", "precio": 25000, "ganancia_diaria": 1500, "porcentaje": 6.0},
    6: {"nombre": "Plan Empresarial", "precio": 50000, "ganancia_diaria": 3250, "porcentaje": 6.5},
    7: {"nombre": "Plan Premium", "precio": 100000, "ganancia_diaria": 7000, "porcentaje": 7.0},
    8: {"nombre": "Plan VIP", "precio": 200000, "ganancia_diaria": 15000, "porcentaje": 7.5},
    9: {"nombre": "Plan Master", "precio": 400000, "ganancia_diaria": 32000, "porcentaje": 8.0},
    10: {"nombre": "Plan Zyronexa Elite", "precio": 1000000, "ganancia_diaria": 100000, "porcentaje": 10.0}
}

def conectar_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def crear_base_datos():
    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            telefono TEXT UNIQUE NOT NULL,
            contrasena TEXT NOT NULL,
            saldo_real INTEGER DEFAULT 0,
            saldo_bono INTEGER DEFAULT 500,
            total_retirado INTEGER DEFAULT 0,
            total_depositado INTEGER DEFAULT 0,
            producto_activo INTEGER DEFAULT 0,
            valor_producto INTEGER DEFAULT 0,
            ganancia_diaria INTEGER DEFAULT 0,
            total_generado INTEGER DEFAULT 0,
            ultima_recompensa TEXT DEFAULT '',
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            es_admin INTEGER DEFAULT 0,
            admin_asignado INTEGER DEFAULT 0,
            stripe_account_id TEXT DEFAULT '',
            precio_plan INTEGER DEFAULT 0,
            fecha_upgrade TIMESTAMP
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historial (
            id SERIAL PRIMARY KEY,
            telefono TEXT NOT NULL,
            tipo TEXT NOT NULL,
            monto INTEGER NOT NULL,
            descripcion TEXT,
            estado TEXT DEFAULT 'completado',
            datos_retiro TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_pago TIMESTAMP,
            notas_pago TEXT,
            comprobante_url TEXT
        );
    """)

    cursor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='historial' AND column_name='stripe_transfer_id') THEN
                ALTER TABLE historial ADD COLUMN stripe_transfer_id TEXT;
            END IF;

            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='historial' AND column_name='stripe_payout_id') THEN
                ALTER TABLE historial ADD COLUMN stripe_payout_id TEXT;
            END IF;
        END $$;
    """)

    conexion.commit()
    cursor.close()
    conexion.close()


crear_base_datos()


@app.route("/")
def index():
    if "usuario" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/registro", methods=["POST"])
def registro():
    datos = request.get_json(silent=True) or request.form
    nombre = datos.get("nombre", "").strip()
    telefono = datos.get("telefono", "").strip()
    contrasena = datos.get("contrasena") or datos.get("password", "")

    if not all([nombre, telefono, contrasena]):
        return jsonify({"success": False, "error": "Todos los campos son obligatorios"}), 400

    contrasena_hash = generate_password_hash(contrasena)

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            INSERT INTO usuarios (nombre, telefono, contrasena, saldo_real, saldo_bono)
            VALUES (%s, %s, %s, 0, 500)
            RETURNING *
        """, (nombre, telefono, contrasena_hash))

        usuario = cursor.fetchone()
        conexion.commit()

        session["usuario"] = dict(usuario)
        session["usuario_id"] = usuario["id"]

        return jsonify({"success": True, "redirect": "/dashboard"})

    except Exception as e:
        conexion.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        cursor.close()
        conexion.close()


@app.route("/login", methods=["POST"])
def login():
    datos = request.get_json()
    telefono = datos.get("telefono")
    contrasena = datos.get("password")

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM usuarios WHERE telefono = %s", (telefono,))
    usuario = cursor.fetchone()

    cursor.close()
    conexion.close()

    if usuario and check_password_hash(usuario["contrasena"], contrasena):
        session["usuario"] = dict(usuario)
        session["usuario_id"] = usuario["id"]
        return jsonify({"success": True, "redirect": "/dashboard"})

    return jsonify({"success": False, "error": "Credenciales incorrectas"}), 401


@app.route("/dashboard")
def dashboard():
    if "usuario" not in session:
        return redirect("/login")
    return render_template("dashboard.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# =========================
# PROPIETARIO
# =========================

@app.route("/propietario")
def propietario_dashboard():
    return "Panel propietario"


# =========================
# RETIRO
# =========================

@app.route("/retirar", methods=["POST"])
def retirar():
    data = request.json
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
