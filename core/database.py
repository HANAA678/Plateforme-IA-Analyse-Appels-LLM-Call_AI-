import os
import psycopg2
from psycopg2.extras import RealDictCursor

# 1. Récupération des variables d'environnement (GCP ou Local)
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "hanaa")  # "hanaa" par défaut pour votre local
DB_NAME = os.getenv("DB_NAME", "callai")
INSTANCE_CONNECTION_NAME = os.getenv("INSTANCE_CONNECTION_NAME")

try:
    if INSTANCE_CONNECTION_NAME:
        # Configuration pour PRODUCTION (Google Cloud Run)
        # On utilise le socket Unix fourni par GCP dans /cloudsql/
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            host=f"/cloudsql/{INSTANCE_CONNECTION_NAME}",
            connect_timeout=10
        )
    else:
        # Configuration pour le LOCAL (votre machine)
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            host="localhost",
            port="5432",
            connect_timeout=10
        )
        
    conn.autocommit = False

except Exception as e:
    print("CRITICAL: Impossible de se connecter à la base de données :", e)
    raise e


# --- Vos fonctions restent strictement identiques et inchangées ---

def execute(query, params=None):
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        print("DB ERROR:", e)


def fetchone(query, params=None):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(query, params)
    result = cur.fetchone()
    cur.close()
    return result


def fetchall(query, params=None):
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(query, params)
    result = cur.fetchall()
    cur.close()
    return result
