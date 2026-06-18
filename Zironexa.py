from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import stripe

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
COMISION_PROPIETARIO = 0.10

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

    # Tabla usuarios
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

    # Tabla historial
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

    # MIGRACIÓN: Si la tabla historial ya existía sin columna telefono, la agregamos
    cursor.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='historial' AND column_name='telefono'
        ) THEN
            ALTER TABLE historial ADD COLUMN telefono TEXT NOT NULL DEFAULT '';
        END IF;
    END $$;
    """)

    conexion.commit()
    cursor.close()
    conexion.close()
    print("Base de datos verificada y migrada correctamente")

def calcular_ganancia_producto(producto_id):
    precios = {1: 500, 2: 1000, 3: 1500, 4: 2000, 5: 3000}
    precio = precios.get(producto_id, 0)
    return int(precio * 0.04)

def obtener_precio_producto(producto_id):
    precios = {1: 500, 2: 1000, 3: 1500, 4: 2000, 5: 3000}
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
            return jsonify({"success": False, "error": "Todos los campos son requeridos"}), 400

        conexion = conectar_db()
        cursor = conexion.cursor()
        cursor.execute("SELECT id FROM usuarios WHERE telefono = %s", (telefono,))
        if cursor.fetchone():
            cursor.close()
            conexion.close()
            return jsonify({"success": False, "error": "Este número ya está registrado"}), 400

        password_hash = generate_password_hash(password)

        cursor.execute("""
        INSERT INTO usuarios (nombre, telefono, password, banco, saldo)
        VALUES (%s, %s, %s, %s, 500)
        """, (nombre, telefono, password_hash, banco))

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "redirect": "/dashboard", "message": "Registro exitoso"})

    except Exception as e:
        print(f"Error registro: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

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
        return jsonify({"success": False, "error": "Teléfono o contraseña incorrectos"}), 401

    except Exception as e:
        print(f"Error login: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/dashboard")
def dashboard():
    if "usuario" not in session:
        return render_template("index.html")

    usuario_session = session["usuario"]

    if usuario_session["es_admin"] == 2:
        return render_template("index.html")

    conexion = conectar_db()
    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("SELECT * FROM usuarios WHERE id = %s", (usuario_session["id"],))
        usuario = cursor.fetchone()

        if not usuario:
            session.clear()
            return render_template("index.html")

        cursor.execute("SELECT * FROM historial WHERE telefono = %s ORDER BY fecha DESC LIMIT 20", (usuario_session["telefono"],))
        historial = cursor.fetchall()

    except Exception as e:
        print(f"Error dashboard query: {e}")
        usuario = {
            "nombre": usuario_session["nombre"],
            "telefono": usuario_session["telefono"],
            "saldo": 0,
            "producto_activo": 0,
            "ganancia_diaria": 0,
            "total_generado": 0,
            "total_retirado": 0
        }
        historial = []
    finally:
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

    try:
        cursor.execute("SELECT * FROM historial ORDER BY fecha DESC LIMIT 50")
        historial = cursor.fetchall()
    except:
        historial = []

    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE es_admin!= 2")
    total_usuarios = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE producto_activo > 0")
    productos_activos = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as total FROM usuarios WHERE es_admin = 1")
    total_admins = cursor.fetchone()["total"]

    try:
        cursor.execute("SELECT COUNT(*) as total FROM historial WHERE tipo = 'retiro' AND descripcion LIKE '%pendiente%'")
        retiros_pendientes = cursor.fetchone()["total"]
    except:
        retiros_pendientes = 0

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

        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo - %s, producto_activo = %s, valor_producto = %s, ganancia_diaria = %s
        WHERE id = %s
        """, (valor, producto_id, valor, ganancia_diaria, usuario_session["id"]))

        id_propietario = crear_o_obtener_propietario(cursor)
        cursor.execute("UPDATE usuarios SET saldo = saldo + %s, ganancias = ganancias + %s WHERE id = %s", (valor, valor, id_propietario))

        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'compra', %s, %s)", (usuario_session["telefono"], valor, f"Compra Plan Nivel {producto_id}"))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'comision', %s, %s)", (PROPIETARIO_TELEFONO, valor, f"Venta Plan Nivel {producto_id} a {usuario_session['telefono']}"))

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

        cursor.execute("""
        UPDATE usuarios
        SET saldo = saldo + %s, ganancias = ganancias + %s, total_generado = total_generado + %s, ultima_recompensa = %s
        WHERE id = %s
        """, (ganancia_usuario, ganancia_usuario, ganancia_usuario, hoy, usuario_session["id"]))

        id_propietario = crear_o_obtener_propietario(cursor)
        cursor.execute("UPDATE usuarios SET saldo = saldo + %s, ganancias = ganancias + %s WHERE id = %s", (comision_propietario, comision_propietario, id_propietario))

        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'recompensa', %s, 'Recompensa diaria 4%')", (usuario_session["telefono"], ganancia_usuario))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'comision', %s, %s)", (PROPIETARIO_TELEFONO, comision_propietario, f"Comisión 10% de {usuario_session['telefono']}"))

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

        cursor.execute("UPDATE usuarios SET saldo = saldo - %s, total_retirado = total_retirado + %s WHERE id = %s", (monto, monto, usuario_session["id"]))
        cursor.execute("INSERT INTO historial (telefono, tipo, monto, descripcion) VALUES (%s, 'retiro', %s, 'Retiro pendiente de aprobación')", (usuario_session["telefono"], monto))

        conexion.commit()
        cursor.close()
        conexion.close()

        return jsonify({"success": True, "message": "Solicitud de retiro enviada"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/logout")
def logout():
    session.clear()
    return render_template("index.html")

if __name__ == "__main__":
    crear_base_datos()
    app.run(host="0.0.0.0", port=5000, debug=False)@app.route("/logout")
def logout():
    session.clear()
    return render_template("index.html")

if __name__ == "__main__":
    crear_base_datos()
    app.run(host="0.0.0.0", port=5000, debug=False)
