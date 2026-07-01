import os
import stripe
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, flash
from datetime import datetime
import pytz
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
import requests  # <- AGREGA ESTA LÍNEA
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clave_secreta_123")

UPLOAD_FOLDER = 'static/comprobantes'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_ACCOUNT_ID = os.getenv("STRIPE_ACCOUNT_ID")

PROPIETARIO_TELEFONO = "84907210"
PASSWORD_PROPIETARIO = os.getenv("PASSWORD_PROPIETARIO", "123456")
TIPO_CAMBIO = 36
MIN_RETIRO_CORDOBAS = 360

client = Client(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_SECRET_KEY")
)
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

PLATAFORMAS = {
    'tiktok': {'dominios': ['tiktok.com'], 'regex': r'/video/(\d+)'},
    'youtube': {'dominios': ['youtube.com', 'youtu.be'], 'regex': [r'v=([A-Za-z0-9_-]{11})', r'youtu\.be/([A-Za-z0-9_-]{11})']},
    'instagram': {'dominios': ['instagram.com'], 'regex': r'/(reel|p)/([A-Za-z0-9_-]+)'},
    'facebook': {'dominios': ['facebook.com', 'fb.watch'], 'regex': [r'v=(\d+)', r'fb\.watch/([A-Za-z0-9_-]+)']},
    'vimeo': {'dominios': ['vimeo.com'], 'regex': r'vimeo\.com/(\d+)'},
    'twitch': {'dominios': ['twitch.tv'], 'regex': r'/videos/(\d+)'},
    'kwai': {'dominios': ['kwai.com', 'kuaishou.com'], 'regex': r'/video/([A-Za-z0-9_-]+)'}
}

PALABRAS_BLOQUEADAS = [
    'xxx','porn','sex','porno','desnuda','desnudo','erotic','escort','caliente',
    'onlyfans','fansly','chaturbate','cam4','brazzers','youporn','xvideos','xnxx',
    'casino','apuesta','apuestas','binarias','forex','crypto','telegram','whatsapp'
]
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
            comprobante_url TEXT,
            stripe_transfer_id TEXT,
            stripe_payout_id TEXT
        );
    """)
    
    cursor.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='usuarios' AND column_name='password') THEN
                ALTER TABLE usuarios RENAME COLUMN password TO contrasena;
            END IF;
        END $$;
    """)
    conexion.commit()
    cursor.execute("SELECT id FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO usuarios (nombre, telefono, contrasena, es_admin, stripe_account_id)
            VALUES (%s, %s, %s, 1, %s)
        """, ("Admin Zyronexa", PROPIETARIO_TELEFONO, generate_password_hash(PASSWORD_PROPIETARIO), STRIPE_ACCOUNT_ID))
        conexion.commit()
    cursor.close()
    conexion.close()

crear_base_datos()

def obtener_saldo(telefono):
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute("SELECT saldo_real FROM usuarios WHERE telefono = %s", (telefono,))
    result = cursor.fetchone()
    cursor.close()
    conexion.close()
    return result[0] if result else 0

def extraer_id_video(url):
    url = url.lower().strip()
    if any(p in url for p in PALABRAS_BLOQUEADAS):
        return None, None, "Link contiene contenido prohibido"
    for plataforma, data in PLATAFORMAS.items():
        if any(d in url for d in data['dominios']):
            regex_list = data['regex'] if isinstance(data['regex'], list) else [data['regex']]
            for regex in regex_list:
                match = re.search(regex, url)
                if match:
                    return match.group(1), plataforma, None
            return None, None, f"Link de {plataforma} inválido"
    return None, None, "Plataforma no soportada. Usa: TikTok, YouTube, Instagram, Facebook, Vimeo, Twitch o Kwai"

@app.route("/")
def index():
    if "usuario" in session:
        next_url = request.args.get('next')
        if next_url:
            if not next_url.startswith('/'):
                next_url = '/' + next_url
            return redirect(next_url)
        return redirect(url_for("videos"))
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
        session["usuario_id"] = usuario["id"]
        return jsonify({"success": True, "redirect": "/videos", "message": "Registro exitoso. Recibiste C$500 de bono"})
    except errors.UniqueViolation:
        conexion.rollback()
        return jsonify({"success": False, "error": "Teléfono ya registrado"}), 400
    except psycopg2.Error as e:
        conexion.rollback()
        print("ERROR DB:", str(e))
        return jsonify({"success": False, "error": "Error interno del servidor"}), 500
    finally:
        cursor.close()
        conexion.close()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "usuario" in session:
            next_url = request.args.get('next', 'videos')
            if not next_url.startswith('/'):
                next_url = '/' + next_url
            return redirect(next_url)
        return render_template("index.html")

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
        session["usuario"] = {
    "id": usuario["id"],
    "telefono": usuario["telefono"],
    "nombre": usuario["nombre"],
    "es_admin": usuario["es_admin"]
}
        session["usuario_id"] = usuario["id"]
        next_url = request.args.get('next', 'videos')
        if not next_url.startswith('/'):
            next_url = '/' + next_url
        return jsonify({"success": True, "redirect": next_url})
    return jsonify({"success": False, "error": "Teléfono o contraseña incorrectos"}), 401

@app.route("/home")
def home():
    if "usuario" not in session:
        return redirect(url_for('index', next='home'))

    user_id = session.get("usuario_id") or session.get("usuario", {}).get("id")
    if not user_id:
        session.clear()
        return redirect(url_for('index', next='home'))
    
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE id = %s", (user_id,))
    usuario = cursor.fetchone()
    cursor.close()
    conexion.close()
    
    if not usuario:
        session.clear()
        return redirect('/login')
    if usuario.get('es_admin') == 1:
        return redirect(url_for("propietario_dashboard"))

    usuario['saldo_total'] = (usuario.get('saldo_real') or 0) + (usuario.get('saldo_bono') or 0)

    return render_template(
        'inversion.html',
        usuario=usuario,
        planes=PLANES,
        stripe_key=STRIPE_PUBLISHABLE_KEY or ""
    )  # <-- solo 1 paréntesis aquí

@app.route("/create-deposit-session", methods=["POST"])
def create_deposit_session():
    if "usuario" not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    data = request.json
    monto_cordobas = int(data.get("monto") or 0)
    
    if monto_cordobas <= 0:
        return jsonify({"error": "Monto inválido"}), 400  # <-- esta línea estaba mal indentada
    
    monto_usd_centavos = int((monto_cordobas / TIPO_CAMBIO) * 100)
    
    if monto_usd_centavos < 50:
        return jsonify({"error": "Monto mínimo no alcanzado"}), 400
    
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

@app.route("/retirar_btc", methods=["POST"])
def retirar_btc():
    if "usuario" not in session:
        return jsonify({"error": "No autorizado"}), 401

    data = request.json
    monto_cordobas = int(data.get("monto") or 0)
    wallet_btc = data.get("wallet", "").strip()

    if monto_cordobas < MIN_RETIRO_CORDOBAS:
        return jsonify({"error": f"Minimo C${MIN_RETIRO_CORDOBAS}"}), 400
    if not wallet_btc:
        return jsonify({"error": "Wallet BTC requerida"}), 400

    telefono = session["usuario"]["telefono"]
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT saldo_real FROM usuarios WHERE id = %s", (session["usuario"]["id"],))
    usuario = cursor.fetchone()

    if monto_cordobas > usuario["saldo_real"]:
        cursor.close(); conexion.close()
        return jsonify({"error": "Saldo insuficiente"}), 400

    try:
        usdt_amount = round(monto_cordobas / TIPO_CAMBIO, 2)
        order = client.order_market_buy(symbol='BTCUSDT', quoteOrderQty=usdt_amount)
        btc_amount = float(order['executedQty'])

        cursor.execute("UPDATE usuarios SET saldo_real = saldo_real - %s WHERE id = %s", (monto_cordobas, session["usuario"]["id"]))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion, estado) VALUES (%s, 'retiro_btc', %s, %s, 'completado')",
                       (telefono, monto_cordobas, f'Compra {btc_amount} BTC a wallet {wallet_btc[:8]}...'))
        conexion.commit()

        # OJO: Sin IP fija y sin 'Retiros' marcado, esto no corre
        # client.withdraw(coin='BTC', address=wallet_btc, amount=btc_amount)

        return jsonify({"success": True, "btc": btc_amount, "msg": "BTC comprado. Retira manual desde Binance."})

    except BinanceAPIException as e:
        conexion.rollback()
        return jsonify({"error": f"Binance: {e.message}"}), 500
    finally:
        cursor.close(); conexion.close()

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

    nical_tz = pytz.timezone('America/Managua')
    hoy_nical_str = datetime.now(nical_tz).strftime('%Y-%m-%d')

    if usuario["ultima_recompensa"] == hoy_nical_str:
        cursor.close()
        conexion.close()
        return jsonify({"error": "Ya cobraste hoy. Vuelve después de las 12:00am"}), 400

    ganancia_usuario = usuario["ganancia_diaria"]
    comision_propietario = int(ganancia_usuario * 0.10)

    cursor.execute("""
        UPDATE usuarios SET saldo_real = saldo_real + %s, total_generado = total_generado + %s, ultima_recompensa = %s
        WHERE id = %s
    """, (ganancia_usuario, ganancia_usuario, hoy_nical_str, usuario["id"]))

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
        WHERE h.tipo='retiro' ORDER BY h.fecha DESC
    """)
    retiros = cursor.fetchall()
    for r in retiros:
        r['datos'] = json.loads(r['datos_retiro']) if r['datos_retiro'] else {}
    retiros_pendientes = [r for r in retiros if r['estado'] == 'pendiente']
    retiros_hoy = [r for r in retiros if r['estado'] == 'pagado' and r['fecha_pago'] and r['fecha_pago'].date() == datetime.now().date()]
    cursor.execute("""
        SELECT COALESCE(SUM((datos_retiro::json->>'monto_neto')::int), 0) as total
        FROM historial WHERE tipo='retiro' AND estado='pagado' AND DATE(fecha_pago)=CURRENT_DATE
    """)
    total_hoy = cursor.fetchone()['total'] or 0
    cursor.execute("SELECT * FROM usuarios WHERE telefono!= %s ORDER BY id DESC", (PROPIETARIO_TELEFONO,))
    usuarios = cursor.fetchall()
    cursor.execute("SELECT * FROM historial WHERE telefono = %s ORDER BY fecha DESC LIMIT 20", (PROPIETARIO_TELEFONO,))
    historial = cursor.fetchall()
    
    # <- AGREGA ESTAS 6 LÍNEAS PARA LOS VIDEOS
    cursor.execute("SELECT COUNT(*) as total FROM videos_propuestos WHERE estado = 'pendiente'")
    videos_pendientes = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM videos_propuestos WHERE estado = 'aprobado'")
    videos_aprobados = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM videos_propuestos WHERE estado = 'rechazado'")
    videos_rechazados = cursor.fetchone()['total']
    cursor.execute("SELECT * FROM videos_propuestos WHERE estado = 'pendiente' ORDER BY fecha_propuesta DESC")
    lista_videos_pendientes = cursor.fetchall()
    
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
        propietario=propietario,
        stats=stats,
        usuarios=usuarios,
        historial=historial,
        retiros=retiros,
        retiros_pendientes=retiros_pendientes,
        retiros_hoy=retiros_hoy,
        planes=PLANES,
    # CAMBIA ESTAS 2 LÍNEAS:
        videos_pendientes=lista_videos_pendientes,  # <- antes era el número, ahora es la lista
        videos_reportados=[]  # <- agrega esta si no tienes reportados aún
    )
@app.route("/marcar_pagado/<int:id>", methods=["POST"])
def marcar_pagado(id):
    if "usuario" not in session or session["usuario"]["telefono"]!= PROPIETARIO_TELEFONO:
        return jsonify({"error": "No autorizado"}), 401
    notas = request.form.get('notas', '')
    comprobante = request.files.get('comprobante')
    url_comprobante = None
    if comprobante and comprobante.filename != '':
        filename = secure_filename(f"retiro_{id}_{datetime.now().timestamp()}.jpg")
        path = os.path.join(UPLOAD_FOLDER, filename)
        comprobante.save(path)
        url_comprobante = f"/{path}"

    conexion = conectar_db()
    cursor = conexion.cursor()
    
    # LOG 2: Ver estado actual antes de actualizar
    cursor.execute("SELECT id, estado FROM historial WHERE id = %s", (id,))
    antes = cursor.fetchone()
    print(f"Estado antes: {antes}") 
    
    cursor.execute("""
        UPDATE historial SET estado='pagado', fecha_pago=CURRENT_TIMESTAMP, notas_pago=%s, comprobante_url=%s
        WHERE id=%s AND estado='pendiente'
    """, (notas, url_comprobante, id))
    
    print(f"Filas afectadas: {cursor.rowcount}") # LOG 3
    
    if cursor.rowcount == 0:
        conexion.rollback()
        cursor.close()
        conexion.close()
        print("ERROR: No se actualizó nada") 
        return jsonify({"error": "Este retiro ya fue pagado o no existe"}), 400

    conexion.commit()
    cursor.close()
    conexion.close()
    print("SUCCESS: Actualizado correctamente")
    return jsonify({"success": True})
@app.route("/exportar_retiros_hoy")
def exportar_retiros_hoy():
    if "usuario" not in session or session["usuario"]["telefono"] != PROPIETARIO_TELEFONO:
        return redirect(url_for("index"))
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT h.id, u.nombre, u.telefono,
               (h.datos_retiro::json->>'banco') as banco,
               (h.datos_retiro::json->>'monto_neto')::int as monto_pagar,
               h.notas_pago, h.fecha_pago
        FROM historial h
        JOIN usuarios u ON h.telefono = u.telefono
        WHERE h.tipo='retiro' AND h.estado='pagado' AND DATE(h.fecha_pago) = CURRENT_DATE
    """)
    datos = cursor.fetchall()
    cursor.close()
    conexion.close()
    df = pd.DataFrame(datos)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f'retiros_{datetime.now().strftime("%Y%m%d")}.xlsx')

@app.route("/sync_ganancias_admin", methods=["POST"])
def sync_ganancias_admin():
    if "usuario" not in session or session["usuario"]["telefono"] != PROPIETARIO_TELEFONO:
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
    
@app.route("/videos")
def videos():
    if "usuario" not in session:
        return redirect(url_for('index', next='videos'))
    
    # 1. El frontend ahora manda ?categoria=general, no ?cat=
    categoria = request.args.get("categoria", "general").lower()
    
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    
    # 2. Query con nombres de columna ya arreglados: id, video_id, etc
    cursor.execute("""
        SELECT 
            v.id, 
            v.video_id, 
            v.plataforma, 
            v.titulo, 
            v.telefono_creador, 
            v.categoria,
            v.estado,
            u.nombre
        FROM public.videos v
        LEFT JOIN usuarios u ON v.telefono_creador = u.telefono
        WHERE v.estado = 'activo' 
        AND LOWER(v.categoria) = %s
        ORDER BY v.fecha_creacion DESC 
        LIMIT 20
    """, (categoria,))
    
    videos_db = cursor.fetchall()
    cursor.close()
    conexion.close()
    
    # 3. Pasa cat_actual para que se marque la pestaña activa
    return render_template("feed_videos.html", videos=videos_db, cat_actual=categoria)
@app.route("/proponer_video", methods=["GET", "POST"])
def proponer_video():
    if "usuario" not in session:
        if request.method == "GET":
            return redirect("/login")
        return jsonify({"error": "No autorizado"}), 401
    
    if request.method == "GET":
        return render_template("proponer_video.html")
    
    if request.method == "POST":
        data = request.get_json()
        titulo = data.get("titulo", "").strip()
        categoria = data.get("categoria", "general").lower()
        url_original = data.get("url_video", "").strip()
        
        if not all([titulo, categoria, url_original]):
            return jsonify({"error": "Faltan datos"}), 400
        
        video_id, plataforma, error = extraer_id_video(url_original)
        
        if error:
            return jsonify({"error": error}), 400
        
        if plataforma == 'tiktok' and ('vt.tiktok.com' in url_original or 'vm.tiktok.com' in url_original):
            video_id_resuelto = resolver_tiktok_url(url_original)
            if not video_id_resuelto:
                return jsonify({"error": "No se pudo resolver el link de TikTok"}), 400
            video_id = video_id_resuelto
        
        if not video_id or not plataforma:
            return jsonify({"error": "No se pudo extraer el ID del video"}), 400
        
        conexion = conectar_db()
        cursor = conexion.cursor()
        try:
            cursor.execute("""
                INSERT INTO videos_propuestos 
                (telefono_creador, nombre, titulo, categoria, plataforma, video_id, estado)
                VALUES (%s, %s, %s, %s, %s, %s, 'pendiente')
            """, (
                session["usuario"]["telefono"], 
                session["usuario"]["nombre"], 
                titulo, 
                categoria, 
                plataforma, 
                video_id
            ))
            conexion.commit()
            return jsonify({"success": True, "message": "Video enviado para revisión"})
        except Exception as e:
            conexion.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conexion.close()


@app.route("/reportar_video/<int:video_id>", methods=["POST"])
def reportar_video(video_id):
    if "usuario" not in session:
        return jsonify({"error": "Login"}), 401
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute("""
        UPDATE videos SET estado = 'reportado' 
        WHERE "identificacion" = %s AND estado = 'aprobado'
    """, (video_id,))
    conexion.commit()
    cursor.close()
    conexion.close()
    return jsonify({"ok": True})
@app.route("/perfil")
def mi_perfil():
    if "usuario" not in session:
        return redirect(url_for('index', next='perfil'))
    
    telefono = session["usuario"]["telefono"]
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT telefono, fecha_registro, total_depositado FROM usuarios WHERE telefono = %s", (telefono,))
    usuario = cursor.fetchone()
    
    if not usuario:
        cursor.close()
        conexion.close()
        return "Usuario no encontrado", 404

    cursor.execute("""
        SELECT COUNT(*) as total,
               COUNT(CASE WHEN estado='aprobado' THEN 1 END) as aprobados,
               COUNT(CASE WHEN estado='pendiente' THEN 1 END) as pendientes,
               COUNT(CASE WHEN estado='rechazado' THEN 1 END) as rechazados
        FROM videos WHERE telefono_creador = %s
    """, (telefono,))
    stats = cursor.fetchone()
    
    cursor.close()
    conexion.close()
    
    stats_videos = {
        'videos_aprobados': stats['aprobados'] or 0,
        'videos_pendientes': stats['pendientes'] or 0,
        'videos_rechazados': stats['rechazados'] or 0,
        'total_videos': stats['total'] or 0
    }
    
    return render_template("perfil.html", usuario=usuario, stats_videos=stats_videos)
@app.route("/perfil/<telefono>")
def perfil(telefono):
    if "usuario" not in session:
        return redirect(url_for('index', next=f'perfil/{telefono}'))
    
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT telefono, fecha_registro, total_depositado FROM usuarios WHERE telefono = %s", (telefono,))
    datos_user = cursor.fetchone()
    if not datos_user:
        cursor.close()
        conexion.close()
        return "Usuario no encontrado", 404

    usuario = {
        "telefono": datos_user["telefono"], 
        "fecha_creado": datos_user["fecha_registro"], 
        "total_depositado": datos_user["total_depositado"]
    }

    # QUERY CORREGIDO ↓
    cursor.execute("""
        SELECT "ID de vídeo" as video_id, plataforma 
        FROM videos
        WHERE telefono_creador = %s AND estado = 'aprobado'
        ORDER BY "identificacion" DESC LIMIT 30
    """, (telefono,))
    urls_videos = cursor.fetchall()

    cursor.close()
    conexion.close()
    return render_template("perfil.html",
                          usuario=usuario,
                          videos_propuestos=len(urls_videos),
                          urls_videos=urls_videos)
@app.route("/aprobar_video/<int:id>", methods=["POST"])
def aprobar_video(id):
    if "usuario" not in session or session["usuario"]["telefono"]!= PROPIETARIO_TELEFONO:
        return jsonify({"error": "No autorizado"}), 401
    
    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    
    try:
        cursor.execute("SELECT * FROM videos_propuestos WHERE id = %s", (id,))
        video = cursor.fetchone()
        
        if not video:
            return jsonify({"error": "Video no encontrado"}), 404
        
        cursor.execute("""
            INSERT INTO videos (telefono_creador, "ID de video", plataforma, titulo, "categorías", estado)
            VALUES (%s, %s, %s, %s, %s, 'aprobado')
            ON CONFLICT ("ID de video", plataforma) DO NOTHING
        """, (
            video['telefono_creador'], 
            video['video_id'],
            video['plataforma'],
            video['titulo'], 
            video['categoria'].lower()
        ))
        
        cursor.execute("UPDATE videos_propuestos SET estado = 'aprobado' WHERE id = %s", (id,))
        conexion.commit()
        return jsonify({"success": True})
    
    except Exception as e:
        conexion.rollback()
        print(f"[APROBAR] ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conexion.close()

@app.route("/rechazar_video/<int:id>", methods=["POST"])
def rechazar_video(id):
    if "usuario" not in session or session["usuario"]["telefono"]!= PROPIETARIO_TELEFONO:
        return jsonify({"error": "No autorizado"}), 401
    conexion = conectar_db()
    cursor = conexion.cursor()
    cursor.execute("UPDATE videos_propuestos SET estado = 'rechazado' WHERE id = %s", (id,))
    conexion.commit()
    cursor.close()
    conexion.close()
    return jsonify({"success": True})
    
@app.route("/test_binance")
def test_binance():
    try:
        account = client.get_account()
        usdt = [b for b in account['balances'] if b['asset'] == 'USDT'][0]
        return jsonify({"ok": True, "USDT_disponible": usdt['free']})
    except BinanceAPIException as e:
        return jsonify({"ok": False, "error": e.message}), 500
if __name__ == "__main__":
    app.run(debug=True)
