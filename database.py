import os
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def configurar_db(app):

    DATABASE_URL = os.getenv("DATABASE_URL")


    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://",
            "postgresql://",
            1
        )


    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


    db.init_app(app)
