import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "zironexa.db")

def conectar_db():
    conexion = sqlite3.connect(DB_NAME)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion

def crear_base_datos():
    try:
        conexion = conectar_db()
        cursor = conexion.cursor()

        # TABLA USUARIOS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL UNIQUE,
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
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # TABLA HISTORIAL
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                monto REAL NOT NULL,
                descripcion TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
            )
        """)

        # TABLA PRODUCTOS
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                precio INTEGER,
                ganancia_diaria INTEGER
            )
        """)

        conexion.commit()
        conexion.close()
        print("\n✅ Base de datos inicializada correctamente")
    except Exception as e:
        print(f"\n❌ Error al crear base de datos: {e}")

def reclamar_ganancias():
    try:
        conexion = conectar_db()
        cursor = conexion.cursor()

        usuarios = cursor.execute(
            "SELECT * FROM usuarios"
        ).fetchall()

        fecha_actual = datetime.now().strftime("%Y-%m-%d")
        hora_actual = datetime.now().hour

        for usuario in usuarios:
            if usuario["producto_activo"] == 0:
                continue

            ultima = usuario["ultima_recompensa"]

            if ultima == fecha_actual:
                continue

            if hora_actual >= 6:
                nuevo_saldo = (
                    usuario["saldo"]
                    +
                    usuario["ganancia_diaria"]
                )

                total_generado = (
                    usuario["total_generado"]
                    +
                    usuario["ganancia_diaria"]
                )

                cursor.execute("""
                    UPDATE usuarios
                    SET
                    saldo = ?,
                    total_generado = ?,
                    ultima_recompensa = ?
                    WHERE id = ?
                """, (
                    nuevo_saldo,
                    total_generado,
                    fecha_actual,
                    usuario["id"]
                ))

        conexion.commit()
        conexion.close()
    except Exception as e:
        print(f"Error al reclamar ganancias: {e}")

# Inicializar DB al importar
crear_base_datos()
