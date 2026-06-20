import os
import stripe
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors # Para capturar UniqueViolation
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import re
import json # AGREGADO
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
LIMITE_DIARIO_BAMPRO = 29000 # AGREGADO: Límite BAMPRO Ahorro Fácil

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
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='historial' AND column_name='estado') THEN
                ALTER TABLE historial ADD COLUMN estado TEXT DEFAULT 'completado';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='historial' AND column_name='datos_retiro') THEN
                ALTER TABLE historial ADD COLUMN datos_retiro TEXT;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='usuarios' AND column_name='precio_plan') THEN
                ALTER TABLE usuarios ADD COLUMN precio_plan INTEGER DEFAULT 0;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                          WHERE table_name='usuarios' AND column_name='fecha_upgrade') THEN
                ALTER TABLE usuarios ADD COLUMN fecha_upgrade TIMESTAMP;
            END IF;
        END $$;
    """)
    conexion.commit()

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

    cursor.execute("SELECT id, contrasena FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    usuario_existente = cursor.fetchone()
    if not usuario_existente:
        cursor.execute("""
            INSERT INTO usuarios (nombre, telefono, contrasena, saldo_real, saldo_bono, es_admin)
            VALUES (%s, %s, %s, 0, 0, 1)
        """, ("Admin Zyronexa", PROPIETARIO_TELEFONO, generate_password_hash(PASSWORD_PROPIETARIO)))
        conexion.commit()
    else:
        if not check_password_hash(usuario_existente[1], PASSWORD_PROPIETARIO):
            cursor.execute("UPDATE usuarios SET contrasena = %s, es_admin = 1 WHERE telefono = %s",
                          (generate_password_hash(PASSWORD_PROPIETARIO), PROPIETARIO_TELEFONO))
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
    if len(nombre) < 3:
        return jsonify({"success": False, "error": "El nombre debe tener al menos 3 caracteres"}), 400
    if not re.match(r'^\d{8}$', telefono):
        return jsonify({"success": False, "error": "El teléfono debe tener 8 dígitos"}), 400
    if len(contrasena) < 6:
        return jsonify({"success": False, "error": "La contraseña debe tener al menos 6 caracteres"}), 400

    contrasena_hash = generate_password_hash(contrasena)
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("""
            INSERT INTO usuarios (nombre, telefono, contrasena, saldo_real, saldo_bono)
            VALUES (%s, %s, %s, 0, 500) RETURNING *
        """, (nombre, telefono, contrasena_hash))
        usuario = cursor.fetchone()
        conexion.commit()
        session["usuario"] = dict(usuario)
        return jsonify({"success": True, "redirect": "/dashboard", "message": "Registro exitoso. Recibiste C$500 de bono"})
    except errors.UniqueViolation:
        conexion.rollback()
        return jsonify({"success": False, "error": "Teléfono ya registrado"}), 400
    except psycopg2.Error as e:
        conexion.rollback()
        print("ERROR DB:", str(e))
        return jsonify({"success": False, "error": "Error de base de datos"}), 500
    finally:
        cursor.close()
        conexion.close()

@app.route("/login", methods=["POST"])
def login():
    datos = request.get_json(silent=True) or request.form
    telefono = datos.get("telefono", "").strip()
    contrasena = datos.get("password") or datos.get("contrasena", "")
    if not telefono or not contrasena:
        return jsonify({"success": False, "error": "Todos los campos son obligatorios"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE telefono = %s", (telefono,))
    usuario = cursor.fetchone()
    cursor.close()
    conexion.close()

    if usuario and check_password_hash(usuario["contrasena"], contrasena):
        session["usuario"] = dict(usuario)
        return jsonify({"success": True, "redirect": "/dashboard"})
    return jsonify({"success": False, "error": "Teléfono o contraseña incorrectos"}), 401

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
    monto_solicitado = int(data.get("monto"))
    metodo = data.get("metodo")
    banco_destino = data.get("banco", "").strip()
    nombre_titular = data.get("nombre_titular", "").strip()
    telefono = session["usuario"]["telefono"]

    if monto_solicitado < 360:
        return jsonify({"error": "Monto mínimo de retiro: C$360"}), 400
    if not nombre_titular:
        return jsonify({"error": "Nombre del titular requerido"}), 400
    if not banco_destino:
        return jsonify({"error": "Banco/Billetera destino requerido"}), 400

    datos_retiro = {}
    if metodo == "tarjeta":
        numero_tarjeta = data.get("numero_tarjeta", "").replace(" ", "")
        if len(numero_tarjeta) < 16:
            return jsonify({"error": "Número de tarjeta inválido"}), 400
        datos_retiro = {"metodo": "tarjeta", "tarjeta": numero_tarjeta, "banco": banco_destino, "titular": nombre_titular}
    elif metodo == "billetera":
        celular_billetera = data.get("celular", "").strip()
        if not re.match(r'^\d{8}$', celular_billetera):
            return jsonify({"error": "Celular de billetera inválido"}), 400
        datos_retiro = {"metodo": "billetera", "celular": celular_billetera, "billetera": banco_destino, "titular": nombre_titular}
    elif metodo == "cuenta":
        numero_cuenta = data.get("numero_cuenta", "").strip()
        if len(numero_cuenta) < 8:
            return jsonify({"error": "Número de cuenta inválido"}), 400
        datos_retiro = {"metodo": "cuenta", "cuenta": numero_cuenta, "banco": banco_destino, "titular": nombre_titular}
    else:
        return jsonify({"error": "Método de retiro no válido"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT saldo_real FROM usuarios WHERE id = %s", (session["usuario"]["id"],))
    usuario = cursor.fetchone()
    if monto_solicitado > usuario["saldo_real"]:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Solo puedes retirar saldo real. El bono no es retirable"}), 400

    comision = int(monto_solicitado * 0.10)
    monto_neto = monto_solicitado - comision
    datos_retiro["monto_neto"] = monto_neto
    datos_retiro["comision"] = comision
    datos_retiro["monto_solicitado"] = monto_solicitado

    cursor.execute("""
        SELECT COALESCE(SUM((datos_retiro::json->>'monto_neto')::int), 0) as total_hoy
        FROM historial WHERE tipo='retiro' AND estado='completado' AND DATE(fecha) = CURRENT_DATE
    """)
    total_hoy = cursor.fetchone()['total_hoy'] or 0
    if total_hoy + monto_neto > LIMITE_DIARIO_BAMPRO:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Límite diario alcanzado. Intenta mañana."}), 400

    cursor.execute("""
        SELECT COUNT(*) as retiros_hoy FROM historial
        WHERE telefono=%s AND tipo='retiro' AND DATE(fecha) = CURRENT_DATE
    """, (telefono,))
    if cursor.fetchone()['retiros_hoy'] > 0:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Solo 1 retiro por día permitido"}), 400

    try:
        cursor.execute("""
        UPDATE usuarios SET saldo_real = saldo_real - %s, total_retirado = total_retirado + %s
        WHERE id = %s
        """, (monto_solicitado, monto_solicitado, session["usuario"]["id"]))
        descripcion = f'Retiro {metodo} a {banco_destino}'
        cursor.execute("""
            INSERT INTO historial (telefono, tipo, monto, descripcion, estado, datos_retiro)
            VALUES (%s, 'retiro', %s, %s, 'pendiente', %s)
        """, (telefono, monto_solicitado, descripcion, json.dumps(datos_retiro)))
        conexion.commit()
        cursor.execute("SELECT saldo_real FROM usuarios WHERE id = %s", (session["usuario"]["id"],))
        session["usuario"]["saldo_real"] = cursor.fetchone()["saldo_real"]
        return jsonify({"success": True, "message": f"Solicitud creada. Recibirás C${monto_neto} en 1-7 días hábiles"})
    except Exception as e:
        conexion.rollback()
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
    if usuario["producto_activo"] > 0 and usuario["valor_producto"] >= precio_plan:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Ya tienes un plan igual o superior"}), 400

    saldo_disponible = usuario["saldo_real"] + usuario["saldo_bono"]
    if usuario["producto_activo"] > 0:
        precio_a_pagar = precio_plan - usuario["valor_producto"]
        mensaje = f"Plan mejorado a {PLANES[plan_valido]['nombre']}"
        es_upgrade = True
    else:
        precio_a_pagar = precio_plan
        mensaje = f"Plan activado: {PLANES[plan_valido]['nombre']}"
        es_upgrade = False

    if saldo_disponible >= precio_a_pagar:
        if usuario["saldo_bono"] >= precio_a_pagar:
            nuevo_bono = usuario["saldo_bono"] - precio_a_pagar
            nuevo_real = usuario["saldo_real"]
        else:
            resto = precio_a_pagar - usuario["saldo_bono"]
            nuevo_bono = 0
            nuevo_real = usuario["saldo_real"] - resto

        cursor.execute("""
        UPDATE usuarios SET
            saldo_bono = %s, saldo_real = %s, producto_activo = %s,
            valor_producto = %s, ganancia_diaria = %s, precio_plan = %s,
            fecha_upgrade = CURRENT_TIMESTAMP
        WHERE id = %s
        """, (nuevo_bono, nuevo_real, plan_valido, precio_plan, ganancia_diaria, precio_plan, usuario["id"]))

        ganancia_propietario = precio_a_pagar if es_upgrade else precio_plan
        cursor.execute("UPDATE usuarios SET saldo_real = saldo_real + %s WHERE telefono = %s", (ganancia_propietario, PROPIETARIO_TELEFONO))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'compra', %s, %s, 'completado')", (usuario["telefono"], precio_a_pagar, mensaje))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'venta', %s, %s, 'completado')", (PROPIETARIO_TELEFONO, ganancia_propietario, mensaje))
        conexion.commit()
        cursor.close()
        conexion.close()
        return jsonify({"success": True, "message": mensaje})
    else:
        monto_faltante = precio_a_pagar - saldo_disponible
        monto_usd = int((monto_faltante / TIPO_CAMBIO) * 100)
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f'{PLANES[plan_valido]["nombre"]} - C${precio_a_pagar}'},
                    "unit_amount": monto_usd,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=url_for("compra_exitosa", _external=True),
            metadata={
                "telefono": usuario["telefono"], "precio_plan": precio_plan, "ganancia_diaria": ganancia_diaria,
                "saldo_usado": saldo_disponible, "plan_id": plan_valido, "es_upgrade": "true" if es_upgrade else "false"
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
    comision_propietario = int(ganancia_usuario * 0.10)
    cursor.execute("""
    UPDATE usuarios SET saldo_real = saldo_real + %s, total_generado = total_generado + %s, ultima_recompensa = %s
    WHERE id = %s
    """, (ganancia_usuario, ganancia_usuario, hoy, usuario["id"]))
    cursor.execute("UPDATE usuarios SET saldo_real = saldo_real + %s WHERE telefono = %s", (comision_propietario, PROPIETARIO_TELEFONO))
    cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'ganancia', %s, 'Ganancia diaria', 'completado')", (usuario["telefono"], ganancia_usuario))
    cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'comision', %s, %s, 'completado')", (PROPIETARIO_TELEFONO, comision_propietario, f'Comisión 10% de {usuario["telefono"]}'))
    conexion.commit()
    cursor.close()
    conexion.close()
    return jsonify({"success": True, "message": f"Ganaste C${ganancia_usuario}. Puedes cobrar todos los días"})

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        return jsonify({"error": "Webhook secret no configurado"}), 500
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError as e:
        return jsonify({"error": "Payload inválido"}), 400
    except stripe.error.SignatureVerificationError as e:
        return jsonify({"error": "Firma inválida"}), 400

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        metadata = session_data.metadata.to_dict() if session_data.metadata else {}
        if not metadata:
            return jsonify({"error": "Sin metadata"}), 400
        try:
            if metadata.get("tipo") == "deposito":
                telefono = metadata["telefono"]
                monto = int(metadata["monto_cordobas"])
                conexion = conectar_db()
                cursor = conexion.cursor()
                # ===== CORREGIDO: Ahora SUMA en vez de reemplazar =====
                cursor.execute("""
                UPDATE usuarios SET saldo_real = saldo_real + %s, total_depositado = total_depositado + %s
                WHERE telefono = %s
                """, (monto, monto, telefono))
                cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'deposito', %s, 'Depósito con tarjeta', 'completado')", (telefono, monto))
                conexion.commit()
                cursor.close()
                conexion.close()
            else:
                required_keys = ["telefono", "precio_plan", "ganancia_diaria", "saldo_usado", "plan_id"]
                if not all(k in metadata for k in required_keys):
                    return jsonify({"error": "Metadata incompleta"}), 400
                telefono = metadata["telefono"]
                precio_plan = int(metadata["precio_plan"])
                ganancia_diaria = int(metadata["ganancia_diaria"])
                saldo_usado = int(metadata["saldo_usado"])
                plan_id = int(metadata["plan_id"])
                es_upgrade = metadata.get("es_upgrade") == "true"
                conexion = conectar_db()
                cursor = conexion.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT saldo_bono, saldo_real, valor_producto FROM usuarios WHERE telefono = %s", (telefono,))
                user_data = cursor.fetchone()
                if not user_data:
                    cursor.close()
                    conexion.close()
                    return jsonify({"error": "Usuario no encontrado"}), 400
                if es_upgrade:
                    precio_a_pagar = precio_plan - user_data["valor_producto"]
                else:
                    precio_a_pagar = precio_plan
                if user_data["saldo_bono"] >= saldo_usado:
                    nuevo_bono = user_data["saldo_bono"] - saldo_usado
                    nuevo_real = user_data["saldo_real"]
                else:
                    nuevo_bono = 0
                    nuevo_real = user_data["saldo_real"] - (saldo_usado - user_data["saldo_bono"])
                cursor.execute("""
                UPDATE usuarios SET saldo_bono = %s, saldo_real = %s, producto_activo = %s,
                    valor_producto = %s, ganancia_diaria = %s, precio_plan = %s, fecha_upgrade = CURRENT_TIMESTAMP
                WHERE telefono = %s
                """, (nuevo_bono, nuevo_real, plan_id, precio_plan, ganancia_diaria, precio_plan, telefono))
                ganancia_propietario = precio_a_pagar if es_upgrade else precio_plan
                mensaje = f'Mejora a {PLANES[plan_id]["nombre"]}' if es_upgrade else f'Compra {PLANES[plan_id]["nombre"]}'
                cursor.execute("UPDATE usuarios SET saldo_real = saldo_real + %s WHERE telefono = %s", (ganancia_propietario, PROPIETARIO_TELEFONO))
                cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'compra', %s, %s, 'completado')", (telefono, precio_a_pagar, mensaje))
                cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'venta', %s, %s, 'completado')", (PROPIETARIO_TELEFONO, ganancia_propietario, mensaje))
                conexion.commit()
                cursor.close()
                conexion.close()
        except Exception as e:
            print(f"ERROR en DB: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
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
    cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'retiro', %s, 'Retiro propietario', 'completado')", (PROPIETARIO_TELEFONO, monto_cordobas))
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
    cursor.execute("SELECT * FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    propietario = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE producto_activo > 0")
    total_usuarios_activos = cursor.fetchone()["total"]
    cursor.execute("SELECT COALESCE(SUM(valor_producto), 0) as total FROM usuarios WHERE producto_activo > 0")
    total_ventas = cursor.fetchone()["total"]
    cursor.execute("SELECT COALESCE(SUM(ganancia_diaria * 0.10), 0) as total FROM usuarios WHERE producto_activo > 0")
    comisiones_diarias = int(cursor.fetchone()["total"])
    cursor.execute("""
        SELECT h.*, u.nombre FROM historial h
        JOIN usuarios u ON h.telefono = u.telefono
        WHERE h.tipo='retiro' AND h.estado='pendiente'
        ORDER BY h.fecha DESC
    """)
    retiros = cursor.fetchall()
    for r in retiros:
        r['datos'] = json.loads(r['datos_retiro']) if r['datos_retiro'] else {}
    cursor.execute("""
        SELECT COALESCE(SUM((datos_retiro::json->>'monto_neto')::int), 0) as total
        FROM historial WHERE tipo='retiro' AND estado='completado' AND DATE(fecha)=CURRENT_DATE
    """)
    total_hoy = cursor.fetchone()['total'] or 0
    cursor.execute("SELECT * FROM usuarios WHERE telefono!= %s ORDER BY id DESC", (PROPIETARIO_TELEFONO,))
    usuarios = cursor.fetchall()
    cursor.execute("SELECT * FROM historial WHERE telefono = %s ORDER BY fecha DESC LIMIT 20", (PROPIETARIO_TELEFONO,))
    historial = cursor.fetchall()
    cursor.close()
    conexion.close()
    stats = {
        "total_ventas": total_ventas,
        "total_usuarios_activos": total_usuarios_activos,
        "comisiones_diarias": comisiones_diarias,
        "total_hoy_bampro": total_hoy,
        "limite_bampro": LIMITE_DIARIO_BAMPRO
    }
    return render_template("propietario.html",
                         propietario=propietario, stats=stats, usuarios=usuarios,
                         historial=historial, retiros=retiros, planes=PLANES)

@app.route("/marcar_pagado/<int:id>", methods=["POST"])
def marcar_pagado(id):
    if "usuario" not in session or session["usuario"]["telefono"]!= PROPIETARIO_TELEFONO:
        return jsonify({"error": "No autorizado"}), 401
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute("UPDATE historial SET estado='completado' WHERE id=%s AND estado='pendiente'", (id,))
    conexion.commit()
    cursor.close()
    conexion.close()
    return jsonify({"success": True})

@app.route("/sync_ganancias_admin", methods=["POST"])
def sync_ganancias_admin():
    if "usuario" not in session or session["usuario"]["telefono"]!= PROPIETARIO_TELEFONO:
        return jsonify({"error": "No autorizado"}), 401
    conexion = conectar_db()
    cursor = conexion.cursor()
    for plan_id, datos in PLANES.items():
        cursor.execute("""
            UPDATE usuarios SET ganancia_diaria = %s, precio_plan = %s
            WHERE producto_activo = %s
        """, (datos['ganancia_diaria'], datos['precio'], plan_id))
    conexion.commit()
    cursor.close()
    conexion.close()
    return jsonify({"success": True, "message": "Usuarios sincronizados"})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
