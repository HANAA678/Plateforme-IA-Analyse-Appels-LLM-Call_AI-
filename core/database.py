import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(
    dbname="callai",
    user="postgres",
    password="hanaa",
    host="localhost",
    port="5432",
    connect_timeout=10
)

conn.autocommit = False


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