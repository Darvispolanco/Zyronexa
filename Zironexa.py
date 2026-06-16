from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import stripe 
import json
# Configuración de rutas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

# Inicializar Flask con rutas explícitas
app = Flask(
    __name__,
    template_folder=TEMPLATE_DIR,
    static_folder=STATIC_DIR
)

app.secret_key = "zyronexa_super_key"
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PROPIETARIO_TELEFONO = "84907210"
PROPIETARIO_PASSWORD = "DarvinFlowX8490"
PROPIETARIO_CUENTA_LAFISE = "139043053"
PROPIETARIO_NOMBRE = "Darvis Polanco"


def conectar_db():

    conexion = psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

    return conexion


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
        cuenta_lafise TEXT DEFAULT '',
        saldo_lafise INTEGER DEFAULT 0,
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
        admin_asignado INTEGER DEFAULT 0
    );
    """)


    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historial (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER REFERENCES usuarios(id),
        tipo TEXT NOT NULL,
        monto REAL NOT NULL,
        descripcion TEXT,
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)


    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono=%s",
        (PROPIETARIO_TELEFONO,)
    )
    propietario = cursor.fetchone()


    if not propietario:

        password_segura = generate_password_hash(
            PROPIETARIO_PASSWORD
        )

        cursor.execute("""
        INSERT INTO usuarios
        (nombre,telefono,password,banco,saldo)
        VALUES (%s,%s,%s,%s,%s)
        """,
        (
        PROPIETARIO_NOMBRE,
        PROPIETARIO_TELEFONO,
        password_segura,
        "LAFISE",
        0
        ))


    conexion.commit()
    conexion.close()


def reclamar_ganancias():
    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()

    fecha_actual = datetime.now().strftime("%Y-%m-%d")
    hora_actual = datetime.now().hour

    if hora_actual < 6:
        conexion.close()
        return

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (PROPIETARIO_TELEFONO,)
    )
    propietario = cursor.fetchone()

    for usuario in usuarios:
        
        if usuario["producto_activo"] == 0:
            continue
        
        if usuario["ultima_recompensa"] == fecha_actual:
            continue
        
        ganancia_usuario = usuario["ganancia_diaria"]

        nuevo_saldo = usuario["saldo"] + ganancia_usuario

        total_generado = usuario["total_generado"] + ganancia_usuario
        
        # Usuario recibe su ganancia
        cursor.execute("""
            UPDATE usuarios
            SET
                saldo = %s,
                total_generado = %s,
                ultima_recompensa = %s
            WHERE id = %s
        """,(
            nuevo_saldo,
            total_generado,
            fecha_actual,
            usuario["id"]
        ))


        # Propietario recibe 10%
        ganancia_propietario = int(ganancia_usuario * 0.10)
        cursor.execute("""
            UPDATE usuarios
            SET saldo = saldo + %s
            WHERE telefono = %s
        """,(
            ganancia_propietario,
            PROPIETARIO_TELEFONO
        ))
# Admin recibe 4%
        if usuario["admin_asignado"] > 0:

            ganancia_admin = int(ganancia_usuario * 0.04)

            cursor.execute("""
                UPDATE usuarios
                SET saldo = saldo + %s
                WHERE id = %s
            """,(
                ganancia_admin,
                usuario["admin_asignado"]
            ))


# Actualizar usuario que generó la ganancia
            cursor.execute("""
                UPDATE usuarios
                SET
                    saldo = %s,
                    total_generado = %s,
                    ultima_recompensa = %s
                WHERE id = %s
            """,(
                nuevo_saldo,
                total_generado,
                fecha_actual,
                usuario["id"]
            ))

    conexion.commit()
    conexion.close()

@app.route("/propietario")
def propietario():
    telefono = session.get("telefono")

    if telefono != PROPIETARIO_TELEFONO:
        return "Acceso denegado"

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (PROPIETARIO_TELEFONO,)
    )
    propietario = cursor.fetchone()

    cursor.execute("""
        SELECT *
        FROM usuarios
        WHERE telefono != %s
        ORDER BY id DESC
    """, (
        PROPIETARIO_TELEFONO,
    ))
    usuarios = cursor.fetchall()

    cursor.execute("""
        SELECT *
        FROM historial
        ORDER BY id DESC
        LIMIT 20
    """)
    historial = cursor.fetchall()

    cursor.execute("""
            SELECT COUNT(*) as total
            FROM usuarios
    """)

    total_usuarios = cursor.fetchone()["total"]
    

    cursor.execute("""
        SELECT COUNT(*) as total
        FROM usuarios
        WHERE producto_activo > 0
    """)
    productos_activos = cursor.fetchone()["total"]
    
    cursor.execute("""
        SELECT COUNT(*) as total
        FROM usuarios
        WHERE es_admin = 1
    """)
    total_admins = cursor.fetchone()["total"]

    conexion.close()

    return render_template(
        "propietario.html",
        propietario=propietario,
        usuarios=usuarios,
        historial=historial,
        total_usuarios=total_usuarios,
        productos_activos=productos_activos,
        cuenta_lafise=PROPIETARIO_CUENTA_LAFISE,
        nombre_lafise=PROPIETARIO_NOMBRE,
        total_admins=total_admins
    )


@app.route("/actualizar_perfil", methods=["POST"])
def actualizar_perfil():
    telefono = session.get("telefono")

    if not telefono:
        return jsonify({"error": "Debes iniciar sesion"}), 401

    datos = request.get_json()
    nuevo_nombre = datos.get("nombre")
    nuevo_banco = datos.get("banco")

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE usuarios
        SET
            nombre = %s,
            banco = %s
        WHERE telefono = %s
    """, (
        nuevo_nombre,
        nuevo_banco,
        telefono
    ))

    conexion.commit()
    conexion.close()

    return jsonify({"mensaje": "Perfil actualizado correctamente"})


@app.route("/comprar_producto", methods=["POST"])
def comprar_producto():
    telefono = session.get("telefono")

    if not telefono:
        return jsonify({"error": "Debes iniciar sesion"}), 401

    datos = request.get_json()
    producto_id = datos.get("producto_id")

    if not producto_id:
        return jsonify({"error": "Producto requerido"}), 400

    try:
        producto_id = int(producto_id)
    except (TypeError, ValueError):
        return jsonify({"error": "Producto invalido"}), 400

    productos = {
        1: {"precio": 500, "ganancia": 20},
        2: {"precio": 1000, "ganancia": 40},
        3: {"precio": 1500, "ganancia": 60},
        4: {"precio": 2000, "ganancia": 80},
        5: {"precio": 3000, "ganancia": 120},
        6: {"precio": 5000, "ganancia": 200},
        7: {"precio": 10000, "ganancia": 400},
        8: {"precio": 20000, "ganancia": 800}
    }

    if producto_id not in productos:
        return jsonify({"error": "Producto invalido"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (telefono,)
    )
    usuario = cursor.fetchone()

    precio = productos[producto_id]["precio"]
    ganancia = productos[producto_id]["ganancia"]

    if usuario["saldo"] < precio:
        conexion.close()
        return jsonify({"error": "No hay saldo suficiente para comprar este producto"}), 400

    if usuario["valor_producto"] >= precio:
        conexion.close()
        return jsonify({"error": "Ya tienes un producto igual o superior"}), 400

    nuevo_saldo = usuario["saldo"] - precio

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (PROPIETARIO_TELEFONO,)
    )
    propietario = cursor.fetchone()

    nuevo_saldo_propietario = propietario["saldo"] + precio

    cursor.execute("""
        UPDATE usuarios
        SET saldo = %s
        WHERE telefono = %s
    """, (
        nuevo_saldo_propietario,
        PROPIETARIO_TELEFONO
    ))

    cursor.execute("""
        UPDATE usuarios
        SET
            saldo = %s,
            producto_activo = %s,
            valor_producto = %s,
            ganancia_diaria = %s
        WHERE telefono = %s
    """, (
        nuevo_saldo,
        producto_id,
        precio,
        ganancia,
        telefono
    ))

    cursor.execute("""
        INSERT INTO historial (
            usuario_id,
            tipo,
            monto,
            descripcion
        )
       VALUES (%s,%s,%s,%s)
    """, (
        usuario["id"],
        "Compra",
        precio,
        f"Compra de producto #{producto_id}"
    ))

    conexion.commit()
    conexion.close()

    return jsonify({"mensaje": "Producto comprado correctamente"})


@app.route("/retirar_lafise", methods=["POST"])
def retirar_lafise():
    telefono = session.get("telefono")

    if not telefono:
        return jsonify({"error": "Debes iniciar sesion"}), 401

    datos = request.get_json()

    try:
        monto = int(datos.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Monto invalido"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (telefono,)
    )
    usuario = cursor.fetchone()

    if monto <= 0:
        conexion.close()
        return jsonify({"error": "Monto invalido"}), 400

    if usuario["saldo"] < monto:
        conexion.close()
        return jsonify({"error": "Saldo insuficiente"}), 400

    nuevo_saldo = usuario["saldo"] - monto
    nuevo_lafise = usuario["saldo_lafise"] + monto
    nuevo_retirado = usuario["total_retirado"] + monto

    cursor.execute("""
        UPDATE usuarios
        SET
            saldo = %s,
            saldo_lafise = %s,
            total_retirado = %s
        WHERE telefono = %s
    """, (
        nuevo_saldo,
        nuevo_lafise,
        nuevo_retirado,
        telefono
    ))

    conexion.commit()
    conexion.close()

    return jsonify({"mensaje": f"{monto} NIO enviados a LAFISE"})


@app.route("/retirar_propietario", methods=["POST"])
def retirar_propietario():
    telefono = session.get("telefono")

    if telefono != PROPIETARIO_TELEFONO:
        return jsonify({"error": "Acceso denegado"}), 403

    datos = request.get_json()

    try:
        monto = int(datos.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Monto invalido"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (PROPIETARIO_TELEFONO,)
    )
    propietario = cursor.fetchone()

    if monto <= 0:
        conexion.close()
        return jsonify({"error": "Monto invalido"}), 400

    if monto > propietario["saldo"]:
        conexion.close()
        return jsonify({"error": "Saldo insuficiente"}), 400

    nuevo_saldo = propietario["saldo"] - monto
    nuevo_lafise = propietario["saldo_lafise"] + monto

    cursor.execute("""
        UPDATE usuarios
        SET
            saldo = %s,
            saldo_lafise = %s
        WHERE telefono = %s
    """, (
        nuevo_saldo,
        nuevo_lafise,
        PROPIETARIO_TELEFONO
    ))

    conexion.commit()
    conexion.close()

    return jsonify({"mensaje": "Retiro realizado correctamente"})


@app.route("/hacer_admin", methods=["POST"])
def hacer_admin():
    if session.get("telefono") != PROPIETARIO_TELEFONO:
        return jsonify({"error": "Acceso denegado"}), 403

    datos = request.get_json()
    usuario_id = datos.get("usuario_id")

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE usuarios
        SET es_admin = 1
        WHERE id = %s
    """, (
        usuario_id,
    ))

    conexion.commit()
    conexion.close()

    return jsonify({"mensaje": "Administrador agregado correctamente"})


@app.route("/quitar_admin", methods=["POST"])
def quitar_admin():
    if session.get("telefono") != PROPIETARIO_TELEFONO:
        return jsonify({"error": "Acceso denegado"}), 403

    datos = request.get_json()
    usuario_id = datos.get("usuario_id")

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE usuarios
        SET
            es_admin = 0,
            admin_asignado = 0
        WHERE id = %s
    """, (
        usuario_id,
    ))

    conexion.commit()
    conexion.close()

    return jsonify({"mensaje": "Administrador removido"})


@app.route("/registro", methods=["POST"])
def registro():
    datos = request.get_json()

    nombre = datos.get("nombre")
    telefono = datos.get("telefono")
    password = datos.get("password")
    banco = datos.get("banco")

    if not nombre or not telefono or not password or not banco:
        return jsonify({"error": "Todos los campos son obligatorios"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (telefono,)
    )
    usuario_existente = cursor.fetchone()

    if usuario_existente:
        conexion.close()
        return jsonify({"error": "Este usuario ya existe"}), 409

    password_segura = generate_password_hash(password)

    cursor.execute("""
        INSERT INTO usuarios (
            nombre,
            telefono,
            password,
            banco,
            saldo
        )
        VALUES (%s,%s,%s,%s,%s)
    """, (
        nombre,
        telefono,
        password_segura,
        banco,
        500
    ))

    conexion.commit()
    session["telefono"] = telefono
    conexion.close()

    return jsonify({
        "mensaje": "Registro exitoso",
        "ir_a": "/usuario"
    })


@app.route("/usuario")
def usuario():
    telefono = session.get("telefono")

    if not telefono:
        return "Debes iniciar sesion"

    reclamar_ganancias()

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (telefono,)
    )
    usuario = cursor.fetchone()

    conexion.close()

    if not usuario:
        return "Usuario no encontrado"

    return render_template("usuario.html", usuario=usuario)

@app.route("/administrador")
def administrador():

    telefono=session.get("telefono")


    conexion=conectar_db()
    cursor=conexion.cursor()


    cursor.execute(
        """
        SELECT * FROM usuarios
        WHERE telefono=%s
        AND es_admin=1
        """,
        (telefono,)
    )
    admin=cursor.fetchone()


    if not admin:
        return "Acceso denegado"

    cursor.execute(
        """
        SELECT * FROM usuarios
        WHERE telefono != %s
        """,
        (PROPIETARIO_TELEFONO,)
    )
    usuarios=cursor.fetchall()

    cursor.execute(
        """
        SELECT COUNT(*) total
        FROM usuarios
        """
    )
    total_usuarios=cursor.fetchone()["total"]

    cursor.execute(
        """
        SELECT COUNT(*) total
        FROM usuarios
        WHERE producto_activo>0
        """
    )
    productos_activos=cursor.fetchone()["total"]



    cursor.execute(
        """
        SELECT * FROM historial
        ORDER BY id DESC
        LIMIT 20
        """
    )
    historial=cursor.fetchall()

    conexion.close()


    return render_template(
        "administrador.html",
        administrador=admin,
        usuarios=usuarios,
        historial=historial,
        total_usuarios=total_usuarios,
        productos_activos=productos_activos
    )

@app.route("/login", methods=["POST"])
def login():
    datos = request.get_json()

    telefono = datos.get("telefono")
    password = datos.get("password")

    if not telefono or not password:
        return jsonify({"error": "Telefono y contrasena obligatorios"}), 400

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = %s",
        (telefono,)
    )
    usuario = cursor.fetchone()

    conexion.close()

    if not usuario:
        return jsonify({"error": "Usuario no encontrado"}), 404

    if not check_password_hash(usuario["password"], password):
        return jsonify({"error": "Contrasena incorrecta"}), 401

    session["telefono"] = telefono

    if telefono == PROPIETARIO_TELEFONO:
        return jsonify({
            "ir_a": "/propietario"
        })


    if usuario["es_admin"] == 1:
        return jsonify({
            "ir_a": "/administrador"
       })


    return jsonify({
        "ir_a": "/usuario"
    })


# =========================
# PAGINA PRINCIPAL
# =========================

@app.route("/")
def inicio():

    print("ENTRANDO AL INDEX")

    return render_template("index.html")



@app.route("/crear_pago", methods=["POST"])
def crear_pago():

    telefono = session.get("telefono")

    if not telefono:
        return jsonify({"error":"Sesión no encontrada"}),401


    datos = request.json

    try:

        dolares = int(datos.get("cantidad"))

        if dolares <= 0:
            return jsonify({"error":"Monto inválido"}),400


        conexion = conectar_db()
        cursor = conexion.cursor()

        cursor.execute(
            "SELECT * FROM usuarios WHERE telefono=%s",
            (telefono,)
        )

        usuario = cursor.fetchone()

        conexion.close()


        pago = stripe.checkout.Session.create(

            mode="payment",

            payment_method_types=[
                "card"
            ],

            line_items=[
                {
                    "price_data":{
                        "currency":"usd",

                        "product_data":{
                            "name":"Saldo Zyronexa"
                        },

                        "unit_amount": dolares * 100
                    },

                    "quantity":1
                }
            ],


            metadata={

                # aquí mandamos el usuario
                "usuario_id": str(usuario["id"]),

                "telefono": telefono,

                # guardamos los dólares
                "dolares": str(dolares)

            },


            success_url=
            "https://zyronexa.onrender.com/usuario?pago=ok",

            cancel_url=
            "https://zyronexa.onrender.com/usuario"

        )


        return jsonify({
            "url":pago.url
        })


    except Exception as e:

        return jsonify({
            "error":str(e)
        }),400

@app.route("/stripe_webhook", methods=["POST"])
def stripe_webhook():
    evento = request.json

    print("WEBHOOK RECIBIDO:")
    print(evento)


    evento = request.json


    if evento["type"] == "checkout.session.completed":


        pago = evento["data"]["object"]


        usuario_id = pago["metadata"]["usuario_id"]


        dolares = float(
            pago["metadata"]["dolares"]
        )


        # Conversión
        monedas = int(dolares * 36)


        conexion = conectar_db()
        cursor = conexion.cursor()


        cursor.execute("""
        UPDATE usuarios
        SET 
        saldo = saldo + %s,
        total_depositado = total_depositado + %s
        WHERE id=%s
        """,
        (
        monedas,
        monedas,
        usuario_id
        ))


        conexion.commit()
        conexion.close()



    return "OK"
# =========================
# EJECUTAR APP
# =========================

try:
    crear_base_datos()
except Exception as e:
    print("Error creando BD:", e)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT",5000)),
        debug=False
    )
