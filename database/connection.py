import os

from pymongo import MongoClient
from pymongo.errors import PyMongoError


MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("DATABASE_NAME", "logismart")


def conectar_mongodb(verbose=True):
    try:
        cliente = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000
        )

        # Verifica que MongoDB responda
        cliente.admin.command("ping")

        db = cliente[DATABASE_NAME]

        if verbose:
            print("[OK] Conexion exitosa con MongoDB")
            print(f"[OK] Base de datos: {DATABASE_NAME}")

        return cliente, db

    except PyMongoError as error:
        if verbose:
            print("[ERROR] No se pudo conectar con MongoDB")
            print(f"Detalle: {error}")
        return None, None


if __name__ == "__main__":
    cliente, db = conectar_mongodb()

    if cliente:
        print("\nColecciones:")
        for coleccion in db.list_collection_names():
            print(f" - {coleccion}")

        cliente.close()
        