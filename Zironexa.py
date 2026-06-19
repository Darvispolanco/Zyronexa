import os
import stripe
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_secreta_123")

# Config Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")

# Config
PROPIETARIO_TELEFONO = "84907210" # Tu número
PASSWORD_PROPIETARIO = os.getenv("PASSWORD_PROPIETARIO", "123456")
TIPO_CAMBIO = 36 # 1 USD = 36 NIO

# Definición de los 10 planes con % escalonado
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
        banco TEXT NOT NULL,
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
        stripe_account_id TEXT DEFAULT ''
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historial (
        id SERIAL PRIMARY KEY,
        telefono TEXT NOT NULL,
        tipo TEXT NOT NULL,
        monto INTEGER NOT NULL,
        descripcion TEXT,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conexion.commit()

    # Renombrar columna password a contrasena si existe
    cursor.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_name='usuarios' AND column_name='password') THEN
                ALTER TABLE usuarios RENAME COLUMN password TO contrasena;
            END IF;
        END $$;
    """)
    conexion.commit()

    # Crear o actualizar usuario propietario
    cursor.execute("SELECT id, contrasena FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    usuario_existente = cursor.fetchone()
    if not usuario_existente:
        cursor.execute("""
            INSERT INTO usuarios (nombre, telefono, contrasena, banco, saldo_real, saldo_bono, es_admin)
            VALUES (%s, %s, %s, %s, 0, 0, 1)
        """, ("Admin Zyronexa", PROPIETARIO_TELEFONO, PASSWORD_PROPIETARIO, "LAFISE"))
        conexion.commit()
    else:
        # Si existe pero la contraseña es diferente, la actualiza
        if usuario_existente[1]!= PASSWORD_PROPIETARIO:
            cursor.execute("UPDATE usuarios SET contrasena = %s, es_admin = 1 WHERE telefono = %s",
                          (PASSWORD_PROPIETARIO, PROPIETARIO_TELEFONO))
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
    datos = request.json
    nombre = datos.get("nombre")
    telefono = datos.get("telefono")
    contrasena = datos.get("contrasena")
    banco = datos.get("banco")

    conexion = conectar_db()
    cursor = conexion.cursor()
    try:
        cursor.execute("""
            INSERT INTO usuarios (nombre, telefono, contrasena, banco, saldo_real, saldo_bono)
            VALUES (%s, %s, %s, %s, 0, 500)
        """, (nombre, telefono, contrasena, banco))
        conexion.commit()
        return jsonify({"success": True, "redirect": "/dashboard", "message": "Registro exitoso. Recibiste C$500 de bono"})
    except psycopg2.Error:
        return jsonify({"success": False, "error": "Teléfono ya registrado"}), 400
    finally:
        cursor.close()
        conexion.close()

@app.route("/login", methods=["POST"])
def login():
    datos = request.json
    telefono = datos.get("telefono")
    contrasena = datos.get("contrasena")

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE telefono = %s AND contrasena = %s", (telefono, contrasena))
    usuario = cursor.fetchone()
    cursor.close()
    conexion.close()

    if usuario:
        session["usuario"] = dict(usuario)
        return jsonify({"success": True, "redirect": "/dashboard"})
    return jsonify({"success": False, "error": "Credenciales incorrectas"}), 401

@app.route("/dashboard")
def dashboard():
    if "usuario" not in session:
        return redirect(url_for("index"))

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE id = %s", (session["usuario"]["id"],))
    usuario = cursor.fetchone()

    if not usuario:
        cursor.close()
        conexion.close()
        session.clear()
        return redirect(url_for("index"))

    session["usuario"] = dict(usuario)

    cursor.execute("SELECT * FROM historial WHERE telefono = %s ORDER BY fecha DESC LIMIT 10", (usuario["telefono"],))
    historial = cursor.fetchall()
    cursor.close()
    conexion.close()

    usuario["saldo_total"] = usuario["saldo_real"] + usuario["saldo_bono"]
    return render_template("usuario.html", usuario=usuario, historial=historial, stripe_key=STRIPE_PUBLISHABLE_KEY, planes=PLANES)

@app.route("/create-deposit-session", methods=["POST"])
def create_deposit_session():
    if "usuario" not in session:
        return jsonify({"error": "No autorizado"}), 401

    data = request.json
    monto_cordobas = int(data.get("monto"))
    monto_usd_centavos = int((monto_cordobas / TIPO_CAMBIO) * 100)

    if monto_usd_centavos < 50:
        return jsonify({"error": "Monto mínimo C$18"}), 400

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Recarga de saldo Zyronexa"},
                    "unit_amount": monto_usd_centavos,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("deposito_exitoso", _external=True),
            cancel_url=url_for("deposito_cancelado", _external=True),
            metadata={
                "telefono": session["usuario"]["telefono"],
                "tipo": "deposito",
                "monto_cordobas": monto_cordobas
            }
        )
        return jsonify({"url": checkout_session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/deposito_exitoso")
def deposito_exitoso():
    return render_template("deposito_exitoso.html")

@app.route("/deposito_cancelado")
def deposito_cancelado():
    return render_template("deposito_cancelado.html")

@app.route("/retirar", methods=["POST"])
def retirar():
    if "usuario" not in session:
        return jsonify({"error": "No autorizado"}), 401

    data = request.json
    monto_cordobas = int(data.get("monto"))

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT saldo_real, telefono FROM usuarios WHERE id = %s", (session["usuario"]["id"],))
    usuario = cursor.fetchone()

    if monto_cordobas > usuario["saldo_real"]:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Solo puedes retirar saldo real. El bono no es retirable"}), 400

    if monto_cordobas < 360:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Monto mínimo de retiro: C$360"}), 400

    try:
        cursor.execute("""
        UPDATE usuarios SET
            saldo_real = saldo_real - %s,
            total_retirado = total_retirado + %s
        WHERE id = %s
        """, (monto_cordobas, monto_cordobas, session["usuario"]["id"]))

        cursor.execute("""
        INSERT INTO historial (telefono, tipo, monto, descripcion)
        VALUES (%s, 'retiro', %s, 'Solicitud de retiro a tarjeta')
        """, (usuario["telefono"], monto_cordobas))

        conexion.commit()
        return jsonify({"success": True, "message": f"Solicitud de retiro por C${monto_cordobas} creada. Se procesará en 1-3 días"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conexion.close()

@app.route("/comprar_plan", methods=["POST"])
def comprar_plan():
    if "usuario" not in session:
        return jsonify({"error": "No autorizado"}), 401

    data = request.json
    precio_plan = int(data.get("precio"))
    ganancia_diaria = int(data.get("ganancia_diaria"))

    # Validar que el plan existe
    plan_valido = None
    for pid, pdata in PLANES.items():
        if pdata["precio"] == precio_plan and pdata["ganancia_diaria"] == ganancia_diaria:
            plan_valido = pid
            break

    if not plan_valido:
        return jsonify({"error": "Plan no válido"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE id = %s", (session["usuario"]["id"],))
    usuario = cursor.fetchone()

    if usuario["producto_activo"] > 0:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Ya tienes un plan activo"}), 400

    saldo_disponible = usuario["saldo_real"] + usuario["saldo_bono"]

    if saldo_disponible >= precio_plan:
        if usuario["saldo_bono"] >= precio_plan:
            nuevo_bono = usuario["saldo_bono"] - precio_plan
            nuevo_real = usuario["saldo_real"]
        else:
            resto = precio_plan - usuario["saldo_bono"]
            nuevo_bono = 0
            nuevo_real = usuario["saldo_real"] - resto

        cursor.execute("""
        UPDATE usuarios SET
            saldo_bono = %s, saldo_real = %s, producto_activo = %s,
            valor_producto = %s, ganancia_diaria = %s
        WHERE id = %s
        """, (nuevo_bono, nuevo_real, plan_valido, precio_plan, ganancia_diaria, usuario["id"]))

        # Tu ganancia: 100% del precio del plan
        cursor.execute("UPDATE usuarios SET saldo_real = saldo_real + %s WHERE telefono = %s", (precio_plan, PROPIETARIO_TELEFONO))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'compra', %s, %s)", (usuario["telefono"], precio_plan, f'Compra {PLANES[plan_valido]["nombre"]}'))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'venta', %s, %s)", (PROPIETARIO_TELEFONO, precio_plan, f'Venta {PLANES[plan_valido]["nombre"]}'))

        conexion.commit()
        cursor.close()
        conexion.close()
        return jsonify({"success": True, "message": "Plan activado para siempre"})
    else:
        monto_faltante = precio_plan - saldo_disponible
        monto_usd = int((monto_faltante / TIPO_CAMBIO) * 100)

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f'{PLANES[plan_valido]["nombre"]} - C${precio_plan}'},
                    "unit_amount": monto_usd,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("compra_exitosa", _external=True),
            metadata={
                "telefono": usuario["telefono"],
                "precio_plan": precio_plan,
                "ganancia_diaria": ganancia_diaria,
                "saldo_usado": saldo_disponible,
                "plan_id": plan_valido
            }
        )
        cursor.close()
        conexion.close()
        return jsonify({"url": checkout_session.url})

@app.route("/compra_exitosa")
def compra_exitosa():
    return render_template("compra_exitosa.html")

@app.route("/cobrar_recompensa", methods=["POST"])
def cobrar_recompensa():
    if "usuario" not in session:
        return jsonify({"error": "No autorizado"}), 401

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE id = %s", (session["usuario"]["id"],))
    usuario = cursor.fetchone()

    if usuario["producto_activo"] == 0:
        cursor.close()
        conexion.close()
        return jsonify({"error": "No tienes producto activo"}), 400

    hoy = datetime.now().strftime('%Y-%m-%d')
    if usuario["ultima_recompensa"] == hoy:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Ya cobraste hoy. Vuelve mañana"}), 400

    ganancia_usuario = usuario["ganancia_diaria"]
    comision_propietario = int(ganancia_usuario * 0.10) # Tu 10% extra

    # Usuario cobra 100% completo
    cursor.execute("""
    UPDATE usuarios SET
        saldo_real = saldo_real + %s,
        total_generado = total_generado + %s,
        ultima_recompensa = %s
    WHERE id = %s
    """, (ganancia_usuario, ganancia_usuario, hoy, usuario["id"]))

    # Tu comisión 10% extra
    cursor.execute("""
    UPDATE usuarios SET saldo_real = saldo_real + %s
    WHERE telefono = %s
    """, (comision_propietario, PROPIETARIO_TELEFONO))

    cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'ganancia', %s, 'Ganancia diaria')", (usuario["telefono"], ganancia_usuario))
    cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'comision', %s, %s)", (PROPIETARIO_TELEFONO, comision_propietario, f'Comisión 10% de {usuario["telefono"]}'))

    conexion.commit()
    cursor.close()
    conexion.close()

    return jsonify({
        "success": True,
        "message": f"Ganaste C${ganancia_usuario}. Puedes cobrar todos los días"
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        metadata = session_data["metadata"]

        if metadata.get("tipo") == "deposito":
            telefono = metadata["telefono"]
            monto = int(metadata["monto_cordobas"])

            conexion = conectar_db()
            cursor = conexion.cursor()
            cursor.execute("""
            UPDATE usuarios SET
                saldo_real = saldo_real + %s,
                total_depositado = total_depositado + %s
            WHERE telefono = %s
            """, (monto, monto, telefono))

            cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'deposito', %s, 'Depósito con tarjeta')", (telefono, monto))
            conexion.commit()
            cursor.close()
            conexion.close()
        else:
            telefono = metadata["telefono"]
            precio_plan = int(metadata["precio_plan"])
            ganancia_diaria = int(metadata["ganancia_diaria"])
            saldo_usado = int(metadata["saldo_usado"])
            plan_id = int(metadata["plan_id"])

            conexion = conectar_db()
            cursor = conexion.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT saldo_bono, saldo_real FROM usuarios WHERE telefono = %s", (telefono,))
            user_data = cursor.fetchone()
            bono_actual = user_data["saldo_bono"]
            real_actual = user_data["saldo_real"]

            if bono_actual >= saldo_usado:
                nuevo_bono = bono_actual - saldo_usado
                nuevo_real = real_actual
            else:
                nuevo_bono = 0
                nuevo_real = real_actual - (saldo_usado - bono_actual)

            cursor.execute("""
            UPDATE usuarios SET
                saldo_bono = %s,
                saldo_real = %s,
                producto_activo = %s,
                valor_producto = %s,
                ganancia_diaria = %s
            WHERE telefono = %s
            """, (nuevo_bono, nuevo_real, plan_id, precio_plan, ganancia_diaria, telefono))

            cursor.execute("UPDATE usuarios SET saldo_real = saldo_real + %s WHERE telefono = %s", (precio_plan, PROPIETARIO_TELEFONO))
            cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'compra', %s, %s)", (telefono, precio_plan, f'Compra {PLANES[plan_id]["nombre"]}'))
            cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'venta', %s, %s)", (PROPIETARIO_TELEFONO, precio_plan, f'Venta {PLANES[plan_id]["nombre"]}'))

            conexion.commit()
            cursor.close()
            conexion.close()

    return jsonify({"success": True}), 200

@app.route("/retirar_propietario", methods=["POST"])
def retirar_propietario():
    if "usuario" not in session or session["usuario"]["telefono"]!= PROPIETARIO_TELEFONO:
        return jsonify({"error": "No autorizado"}), 401

    data = request.json
    monto_cordobas = int(data.get("monto"))

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT saldo_real FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    propietario = cursor.fetchone()

    if monto_cordobas > propietario["saldo_real"]:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Saldo insuficiente"}), 400

    cursor.execute("UPDATE usuarios SET saldo_real = saldo_real - %s WHERE telefono = %s", (monto_cordobas, PROPIETARIO_TELEFONO))
    cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'retiro', %s, 'Retiro propietario')", (PROPIETARIO_TELEFONO, monto_cordobas))
    conexion.commit()
    cursor.close()
    conexion.close()

    return jsonify({"success": True, "message": "Retiro registrado. Haz el Payout manual en Stripe Dashboard"})

@app.route("/propietario")
def propietario_dashboard():
    if "usuario" not in session or session["usuario"]["telefono"]!= PROPIETARIO_TELEFONO:
        return redirect(url_for("index"))

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    # Datos del propietario
    cursor.execute("SELECT * FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    propietario = cursor.fetchone()

    # Stats generales
    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE producto_activo > 0")
    total_usuarios_activos = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(valor_producto), 0) as total FROM usuarios WHERE producto_activo > 0")
    total_ventas = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(ganancia_diaria * 0.10), 0) as total FROM usuarios WHERE producto_activo > 0")
    comisiones_diarias = int(cursor.fetchone()["total"])

    # Lista de usuarios
    cursor.execute("SELECT * FROM usuarios WHERE telefono!= %s ORDER BY id DESC", (PROPIETARIO_TELEFONO,))
    usuarios = cursor.fetchall()

    # Historial solo tuyo
    cursor.execute("SELECT * FROM historial WHERE telefono = %s ORDER BY fecha DESC LIMIT 20", (PROPIETARIO_TELEFONO,))
    historial = cursor.fetchall()

    cursor.close()
    conexion.close()

    stats = {
        "total_ventas": total_ventas,
        "total_usuarios_activos": total_usuarios_activos,
        "comisiones_diarias": comisiones_diarias
    }

    return render_template("propietario.html",
                         propietario=propietario,
                         stats=stats,
                         usuarios=usuarios,
                         historial=historial,
                         planes=PLANES)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
