from flask import Flask, render_template, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import conectar_db, reclamar_ganancias
import os

app = Flask(__name__)
app.secret_key = "zyronexa_super_key"

PROPIETARIO_TELEFONO = "84907210"
PROPIETARIO_PASSWORD = "admin123"

# INICIO
@app.route("/")
def inicio():
    return render_template("index.html")

# USUARIO
@app.route("/usuario")
def usuario():
    telefono = session.get("telefono")
    if not telefono:
        return "Debes iniciar sesion"

    reclamar_ganancias()
    conexion = conectar_db()
    cursor = conexion.cursor()

    usuario = cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = ?",
        (telefono,)
    ).fetchone()
    conexion.close()

    if not usuario:
        return "Usuario no encontrado"

    return render_template(
        "usuario.html",
        usuario=usuario
    )

# PROPIETARIO
@app.route("/propietario")
def propietario():
    return render_template("propietario.html")

# ACTUALIZAR PERFIL
@app.route("/actualizar_perfil", methods=["POST"])
def actualizar_perfil():
    telefono = session.get("telefono")
    if not telefono:
        return jsonify({
            "error": "Debes iniciar sesion"
        }), 401

    datos = request.get_json()
    nuevo_nombre = datos.get("nombre")
    nuevo_banco = datos.get("banco")

    conexion = conectar_db()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE usuarios
        SET
        nombre = ?,
        banco = ?
        WHERE telefono = ?
    """, (
        nuevo_nombre,
        nuevo_banco,
        telefono
    ))

    conexion.commit()
    conexion.close()

    return jsonify({
        "mensaje": "Perfil actualizado correctamente"
    })

# COMPRAR PRODUCTOS
@app.route("/comprar_producto", methods=["POST"])
def comprar_producto():
    telefono = session.get("telefono")
    if not telefono:
        return jsonify({
            "error": "Debes iniciar sesion"
        }), 401

    datos = request.get_json()
    producto_id = datos.get("producto_id")

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
        return jsonify({
            "error": "Producto invalido"
        }), 400

    conexion = conectar_db()
    cursor = conexion.cursor()

    usuario = cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = ?",
        (telefono,)
    ).fetchone()

    precio = productos[producto_id]["precio"]
    ganancia = productos[producto_id]["ganancia"]

    if usuario["saldo"] < precio:
        conexion.close()
        return jsonify({
            "error": "No hay saldo suficiente para comprar este producto"
        }), 400

    producto_actual = usuario["valor_producto"]
    if producto_actual >= precio:
        conexion.close()
        return jsonify({
            "error": "Ya tienes un producto igual o superior"
        }), 400

    nuevo_saldo = usuario["saldo"] - precio

    cursor.execute("""
        UPDATE usuarios
        SET
        saldo = ?,
        producto_activo = ?,
        valor_producto = ?,
        ganancia_diaria = ?
        WHERE telefono = ?
    """, (
        nuevo_saldo,
        producto_id,
        precio,
        ganancia,
        telefono
    ))

    conexion.commit()
    conexion.close()

    return jsonify({
        "mensaje": "Producto comprado correctamente"
    })

# REGISTRO
@app.route("/registro", methods=["POST"])
def registro():
    datos = request.get_json()
    nombre = datos.get("nombre")
    telefono = datos.get("telefono")
    password = datos.get("password")
    banco = datos.get("banco")

    if not nombre or not telefono or not password or not banco:
        return jsonify({
            "error": "Todos los campos son obligatorios"
        }), 400

    conexion = conectar_db()
    cursor = conexion.cursor()

    usuario_existente = cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = ?",
        (telefono,)
    ).fetchone()

    if usuario_existente:
        conexion.close()
        return jsonify({
            "error": "Este usuario ya existe. Inicia sesion."
        }), 409

    password_segura = generate_password_hash(password)

    cursor.execute("""
        INSERT INTO usuarios (
            nombre,
            telefono,
            password,
            banco,
            saldo
        )
        VALUES (?, ?, ?, ?, ?)
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
        "mensaje": "Registro exitoso. Has recibido 500 NIO",
        "ir_a": "/usuario"
    })

# LOGIN
@app.route("/login", methods=["POST"])
def login():
    datos = request.get_json()
    telefono = datos.get("telefono")
    password = datos.get("password")

    if not telefono or not password:
        return jsonify({
            "error": "Telefono y contrasena son obligatorios"
        }), 400

    # LOGIN PROPIETARIO
    if (
        telefono == PROPIETARIO_TELEFONO
        and
        password == PROPIETARIO_PASSWORD
    ):
        session["telefono"] = telefono
        return jsonify({
            "mensaje": "Bienvenido propietario",
            "ir_a": "/propietario"
        })

    conexion = conectar_db()
    cursor = conexion.cursor()

    usuario = cursor.execute(
        "SELECT * FROM usuarios WHERE telefono = ?",
        (telefono,)
    ).fetchone()

    conexion.close()

    if not usuario:
        return jsonify({
            "error": "Usuario no encontrado. Registrate primero."
        }), 404

    if not check_password_hash(
        usuario["password"],
        password
    ):
        return jsonify({
            "error": "Contrasena incorrecta"
        }), 401

    session["telefono"] = telefono

    return jsonify({
        "mensaje": "Inicio de sesion exitoso",
        "ir_a": "/usuario"
    })

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "False") == "True"
    )
