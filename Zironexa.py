from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import stripe
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR,
    static_folder=STATIC_DIR
)

# === VARIABLES DE ENTORNO ===
app.secret_key = os.getenv("SECRET_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
ENDPOINT_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
TIPO_CAMBIO = 36

PROPIETARIO_TELEFONO = os.getenv("PROPIETARIO_TELEFONO")
PROPIETARIO_PASSWORD = os.getenv("PROPIETARIO_PASSWORD")
COMISION_PROPIETARIO = 0.10 # 10% de comisión sobre ganancias

if not all([PROPIETARIO_PASSWORD, app.secret_key, stripe.api_key, ENDPOINT_SECRET]):
    raise ValueError("Faltan variables de entorno críticas. Revisa Render.")

def conectar_db():
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(database_url)

def crear_base_datos():
    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        nombre TEXT NOT NULL,
        telefono TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        banco TEXT NOT NULL,
        saldo INTEGER DEFAULT 500,
        ganancias INTEGER DEFAULT 0,
        total_retirado INTEGER DEFAULT 0,
        total_depositado INTEGER DEFAULT 0,
        productos TEXT DEFAULT '',
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
    cursor.close()
    conexion.close()

# 4% DIARIO DE CADA PLAN
def calcular_ganancia_producto(producto_id):
    precios = {
        1: 500, # Starter
        2: 1500, # Básico
        3: 5000, # Intermedio
        4: 10000, # Avanzado
        5: 25000, # Profesional
        6: 50000, # Empresarial
        7: 100000, # Premium
        8: 200000, # VIP
        9: 400000, # Master
        10: 1000000 # Zyronexa Elite
    }
    precio = precios.get(producto_id, 0)
    return int(precio * 0.04) # 4% diario

def obtener_precio_producto(producto_id):
    precios = {
        1: 500, 2: 1500, 3: 5000, 4: 10000, 5: 25000,
        6: 50000, 7: 100000, 8: 200000, 9: 400000, 10: 1000000
    }
    return precios.get(producto_id, 0)

def crear_o_obtener_propietario(cursor):
    cursor.execute("SELECT id FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    propietario = cursor.fetchone()
    if not propietario:
        cursor.execute("""
        INSERT INTO usuarios (nombre, telefono, password, banco, saldo, es_admin)
        VALUES ('Propietario', %s, %s, 'Ninguno', 0, 2)
        """, (PROPIETARIO_TELEFONO, generate_password_hash(PROPIETARIO_PASSWORD)))
        cursor.execute("SELECT id FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
        propietario = cursor.fetchone()
    return propietario[0]

@app.route("/")
def inicio():
    return render_template("index.html")

@app.route("/registro", methods=["POST"])
def registro():
    try:
        data = request.json
        nombre = data.get("nombre")
        telefono = data.get("telefono")
        password = data.get("password")
        banco = data.get("banco", "Ninguno")

        if not nombre or not telefono or not password:
            return jsonify({"error": "Todos los campos son requeridos"}), 400

        conexion = conectar_db()
        cursor = conexion.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE telefono = %s", (telefono,))
        if cursor.fetchone():
            cursor.close()
            conexion.close()
            return jsonify({"error": "Este número ya está registrado"}), 400

        password_hash = generate_password_hash(password)

        cursor.execute("""
        INSERT INTO usuarios (nombre, telefono, password, banco, saldo)
        VALUES (%s, %s, %s, %s, 500)
        """, (nombre, telefono, password_hash, banco))

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": "Registro exitoso"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.json
        telefono = data.get("telefono")
        password = data.get("password")

        if telefono == PROPIETARIO_TELEFONO and password == PROPIETARIO_PASSWORD:
            session["usuario"] = {
                "telefono": PROPIETARIO_TELEFONO,
                "nombre": "Propietario",
                "es_admin": 2,
                "id": 0
            }
            return jsonify({"success": True, "redirect": "/propietario"})

        conexion = conectar_db()
        cursor = conexion.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM usuarios WHERE telefono = %s", (telefono,))
        usuario = cursor.fetchone()

        if usuario and check_password_hash(usuario["password"], password):
            session["usuario"] = {
                "id": usuario["id"],
                "telefono": usuario["telefono"],
                "nombre": usuario["nombre"],
                "es_admin": usuario["es_admin"]
            }
            cursor.close()
            conexion.close()
            return jsonify({"success": True, "redirect": "/dashboard"})

        cursor.close()
        conexion.close()
        return jsonify({"error": "Teléfono o contraseña incorrectos"}), 401

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/dashboard")
def dashboard():
    if "usuario" not in session:
        return render_template("index.html")

    usuario_session = session["usuario"]

    if usuario_session["es_admin"] == 2:
        return render_template("index.html")

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE id = %s", (usuario_session["id"],))
    usuario = cursor.fetchone()

    cursor.execute("SELECT * FROM historial WHERE telefono = %s ORDER BY fecha DESC LIMIT 20", (usuario_session["telefono"],))
    historial = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template("usuario.html", usuario=usuario, historial=historial)

@app.route("/propietario")
def propietario():
    if "usuario" not in session or session["usuario"]["es_admin"]!= 2:
        return render_template("index.html")

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM usuarios WHERE telefono = %s", (PROPIETARIO_TELEFONO,))
    propietario = cursor.fetchone()

    cursor.execute("SELECT * FROM usuarios WHERE es_admin!= 2 ORDER BY fecha_registro DESC")
    usuarios = cursor.fetchall()

    cursor.execute("SELECT * FROM historial ORDER BY fecha DESC LIMIT 50")
    historial = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE es_admin!= 2")
    total_usuarios = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE producto_activo > 0")
    productos_activos = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE es_admin = 1")
    total_admins = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM historial WHERE tipo = 'retiro' AND descripcion LIKE '%pendiente%'")
    retiros_pendientes = cursor.fetchone()["total"]

    cursor.close()
    conexion.close()

    return render_template(
        "propietario.html",
        propietario=propietario,
        usuarios=usuarios,
        historial=historial,
        total_usuarios=total_usuarios,
        productos_activos=productos_activos,
        total_admins=total_admins,
        retiros_pendientes=retiros_pendientes
    )

@app.route("/comprar_producto", methods=["POST"])
def comprar_producto():
    if "usuario" not in session:
        return jsonify({"error": "No autenticado"}), 401

    try:
        data = request.json
        producto_id = int(data.get("producto_id"))
        valor = int(data.get("valor"))

        usuario_session = session["usuario"]

        conexion = conectar_db()
        cursor = conexion.cursor()

        cursor.execute("SELECT saldo FROM usuarios WHERE id = %s", (usuario_session["id"],))
        saldo_actual = cursor.fetchone()[0]

        if saldo_actual < valor:
            cursor.close()
            conexion.close()
            return jsonify({"error": "Saldo insuficiente"}), 400

        ganancia_diaria = calcular_ganancia_producto(producto_id)

        # 1. Descontar al usuario
        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo - %s,
            producto_activo = %s,
            valor_producto = %s,
            ganancia_diaria = %s
        WHERE id = %s
        """, (valor, producto_id, valor, ganancia_diaria, usuario_session["id"]))

        # 2. Acreditar compra al propietario
        id_propietario = crear_o_obtener_propietario(cursor)
        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo + %s,
            ganancias = ganancias + %s
        WHERE id = %s
        """, (valor, valor, id_propietario))

        # 3. Historial del usuario
        cursor.execute("""
        INSERT INTO historial (telefono, tipo, monto, descripcion)
        VALUES (%s, 'compra', %s, %s)
        """, (usuario_session["telefono"], valor, f"Compra Plan Nivel {producto_id}"))

        # 4. Historial del propietario
        cursor.execute("""
        INSERT INTO historial (telefono, tipo, monto, descripcion)
        VALUES (%s, 'comision', %s, %s)
        """, (PROPIETARIO_TELEFONO, valor, f"Venta Plan Nivel {producto_id} a {usuario_session['telefono']}"))

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": "Producto comprado exitosamente"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/reclamar_recompensa", methods=["POST"])
def reclamar_recompensa():
    if "usuario" not in session:
        return jsonify({"error": "No autenticado"}), 401

    try:
        usuario_session = session["usuario"]

        conexion = conectar_db()
        cursor = conexion.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM usuarios WHERE id = %s", (usuario_session["id"],))
        usuario = cursor.fetchone()

        if usuario["producto_activo"] == 0:
            cursor.close()
            conexion.close()
            return jsonify({"error": "No tienes producto activo"}), 400

        hoy = datetime.now().strftime("%Y-%m-%d")
        if usuario["ultima_recompensa"] == hoy:
            cursor.close()
            conexion.close()
            return jsonify({"error": "Ya reclamaste tu recompensa hoy"}), 400

        ganancia_usuario = usuario["ganancia_diaria"]
        comision_propietario = int(ganancia_usuario * COMISION_PROPIETARIO)

        # 1. Dar ganancia al usuario
        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo + %s,
            ganancias = ganancias + %s,
            total_generado = total_generado + %s,
            ultima_recompensa = %s
        WHERE id = %s
        """, (ganancia_usuario, ganancia_usuario, ganancia_usuario, hoy, usuario_session["id"]))

        # 2. Dar comisión al propietario
        id_propietario = crear_o_obtener_propietario(cursor)
        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo + %s,
            ganancias = ganancias + %s
        WHERE id = %s
        """, (comision_propietario, comision_propietario, id_propietario))

        # 3. Historial usuario
        cursor.execute("""
        INSERT INTO historial (telefono, tipo, monto, descripcion)
        VALUES (%s, 'recompensa', %s, 'Recompensa diaria 4%')
        """, (usuario_session["telefono"], ganancia_usuario))

        # 4. Historial propietario
        cursor.execute("""
        INSERT INTO historial (telefono, tipo, monto, descripcion)
        VALUES (%s, 'comision', %s, %s)
        """, (PROPIETARIO_TELEFONO, comision_propietario, f"Comisión 10% de {usuario_session['telefono']}"))

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": f"Recompensa de C${ganancia_usuario} reclamada"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/retirar", methods=["POST"])
def retirar():
    if "usuario" not in session:
        return jsonify({"error": "No autenticado"}), 401

    try:
        data = request.json
        monto = int(data.get("monto"))
        usuario_session = session["usuario"]

        conexion = conectar_db()
        cursor = conexion.cursor()

        cursor.execute("SELECT saldo FROM usuarios WHERE id = %s", (usuario_session["id"],))
        saldo_actual = cursor.fetchone()[0]

        if saldo_actual < monto:
            cursor.close()
            conexion.close()
            return jsonify({"error": "Saldo insuficiente"}), 400

        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo - %s,
            total_retirado = total_retirado + %s
        WHERE id = %s
        """, (monto, monto, usuario_session["id"]))

        cursor.execute("""
        INSERT INTO historial (telefono, tipo, monto, descripcion)
        VALUES (%s, 'retiro', %s, 'Retiro pendiente de aprobación')
        """, (usuario_session["telefono"], monto))

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": "Solicitud de retiro enviada"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    if "usuario" not in session:
        return jsonify({"error": "No autenticado"}), 401

    try:
        data = request.json
        monto_cordobas = int(data.get("monto"))

        if monto_cordobas < 100:
            return jsonify({"error": "Monto mínimo C$100"}), 400

        monto_usd_centavos = int((monto_cordobas / TIPO_CAMBIO) * 100)
        usuario_session = session["usuario"]

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Depósito Zyronexa",
                        "description": f"Recarga de saldo - C${monto_cordobas}"
                    },
                    "unit_amount": monto_usd_centavos,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=request.host_url + "dashboard?deposito=success",
            cancel_url=request.host_url + "dashboard?deposito=cancel",
            client_reference_id=usuario_session["telefono"],
            metadata={
                "telefono": usuario_session["telefono"],
                "monto_cordobas": monto_cordobas
            }
        )

        return jsonify({"url": checkout_session.url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, ENDPOINT_SECRET
        )
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session_data = event["data"]["object"]
        telefono = session_data["client_reference_id"]
        amount_total = session_data["amount_total"]
        monto_cordobas = int(amount_total / 100 * TIPO_CAMBIO)

        conexion = conectar_db()
        cursor = conexion.cursor()

        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo + %s,
            total_depositado = total_depositado + %s
        WHERE telefono = %s
        """, (monto_cordobas, monto_cordobas, telefono))

        cursor.execute("""
        INSERT INTO historial (telefono, tipo, monto, descripcion)
        VALUES (%s, 'deposito', %s, 'Depósito con tarjeta Stripe')
        """, (telefono, monto_cordobas))

        conexion.commit()
        cursor.close()
        conexion.close()

    return jsonify({"success": True})

@app.route("/modificar_saldo", methods=["POST"])
def modificar_saldo():
    if "usuario" not in session or session["usuario"]["es_admin"]!= 2:
        return jsonify({"error": "No autorizado"}), 401

    try:
        data = request.json
        id_usuario = data.get("id")
        monto = int(data.get("monto"))
        accion = data.get("accion")

        conexion = conectar_db()
        cursor = conexion.cursor()

        if accion == "agregar":
            cursor.execute("UPDATE usuarios SET saldo = saldo + %s WHERE id = %s", (monto, id_usuario))
            mensaje = f"Saldo agregado: C${monto}"
        else:
            cursor.execute("UPDATE usuarios SET saldo = saldo - %s WHERE id = %s", (monto, id_usuario))
            mensaje = f"Saldo retirado: C${monto}"

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": mensaje})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/toggle_admin", methods=["POST"])
def toggle_admin():
    if "usuario" not in session or session["usuario"]["es_admin"]!= 2:
        return jsonify({"error": "No autorizado"}), 401

    try:
        data = request.json
        id_usuario = data.get("id")
        es_admin_actual = data.get("es_admin")
        nuevo_rol = 0 if es_admin_actual == 1 else 1

        conexion = conectar_db()
        cursor = conexion.cursor()
        cursor.execute("UPDATE usuarios SET es_admin = %s WHERE id = %s", (nuevo_rol, id_usuario))
        conexion.commit()
        cursor.close()
        conexion.close()

        mensaje = "Admin removido" if nuevo_rol == 0 else "Usuario promovido a admin"
        return jsonify({"success": True, "message": mensaje})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/aprobar_retiro", methods=["POST"])
def aprobar_retiro():
    if "usuario" not in session or session["usuario"]["es_admin"]!= 2:
        return jsonify({"error": "No autorizado"}), 401

    try:
        data = request.json
        id_historial = data.get("id")

        conexion = conectar_db()
        cursor = conexion.cursor()
        cursor.execute("UPDATE historial SET descripcion = 'Retiro aprobado y completado' WHERE id = %s", (id_historial,))
        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": "Retiro aprobado"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/rechazar_retiro", methods=["POST"])
def rechazar_retiro():
    if "usuario" not in session or session["usuario"]["es_admin"]!= 2:
        return jsonify({"error": "No autorizado"}), 401

    try:
        data = request.json
        id_historial = data.get("id")

        conexion = conectar_db()
        cursor = conexion.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT telefono, monto FROM historial WHERE id = %s", (id_historial,))
        retiro = cursor.fetchone()

        cursor.execute("UPDATE usuarios SET saldo = saldo + %s WHERE telefono = %s", (retiro["monto"], retiro["telefono"]))
        cursor.execute("UPDATE historial SET descripcion = 'Retiro rechazado - saldo devuelto' WHERE id = %s", (id_historial,))

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": "Retiro rechazado y saldo devuelto"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/logout")
def logout():
    session.clear()
    return render_template("index.html")

if __name__ == "__main__":
    crear_base_datos()
    app.run(host="0.0.0.0", port=5000, debug=False)
