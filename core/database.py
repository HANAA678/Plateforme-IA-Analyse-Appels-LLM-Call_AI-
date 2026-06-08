import os
from datetime import datetime, date
from google.cloud import bigquery

# ---------------------------------------------------------------------------
# Configuration – variables d'environnement
# ---------------------------------------------------------------------------
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "dda-dpl-datalab-sdbx-za")
DATASET_ID = os.getenv("BQ_DATASET_ID",  "SpeakFlow")
LOCATION   = os.getenv("BQ_LOCATION",    "europe-west9")
T = f"{PROJECT_ID}.{DATASET_ID}"

# ---------------------------------------------------------------------------
# Initialisation du client BigQuery (ADC uniquement)
# En local  : gcloud auth application-default login
# Sur GCP   : automatique via le compte de service attaché
# ---------------------------------------------------------------------------
try:
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    print(f"BigQuery client initialisé – projet : {PROJECT_ID}, dataset : {DATASET_ID}")
except Exception as e:
    print("CRITICAL: Impossible d'initialiser le client BigQuery :", e)
    raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_table(table: str) -> str:
    """Retourne le nom complet `project.dataset.table`."""
    return f"`{PROJECT_ID}.{DATASET_ID}.{table}`"


def execute(query: str, params: dict | None = None) -> None:
    """
    Exécute une requête DML (INSERT, UPDATE, DELETE, CREATE …).
    Utilise les paramètres nommés BigQuery (@nom).

    Exemple :
        execute(
            f"INSERT INTO {_full_table('Agent')} (id, team_id) VALUES (@id, @team_id)",
            {"id": "abc", "team_id": "xyz"}
        )
    """
    job_config = bigquery.QueryJobConfig()
    if params:
        job_config.query_parameters = [
            bigquery.ScalarQueryParameter(k, _bq_type(v), v)
            for k, v in params.items()
        ]
    try:
        job = client.query(query, job_config=job_config)
        job.result()  # attend la fin du job
    except Exception as e:
        print("BQ EXECUTE ERROR:", e)
        raise


def fetchone(query: str, params: dict | None = None) -> dict | None:
    """
    Retourne la première ligne d'un SELECT sous forme de dict, ou None.
    """
    rows = fetchall(query, params)
    return rows[0] if rows else None


def fetchall(query: str, params: dict | None = None) -> list[dict]:
    """
    Retourne toutes les lignes d'un SELECT sous forme de liste de dicts.
    """
    job_config = bigquery.QueryJobConfig()
    if params:
        job_config.query_parameters = [
            bigquery.ScalarQueryParameter(k, _bq_type(v), v)
            for k, v in params.items()
        ]
    try:
        job = client.query(query, job_config=job_config)
        return [dict(row) for row in job.result()]
    except Exception as e:
        print("BQ FETCHALL ERROR:", e)
        raise


# ---------------------------------------------------------------------------
# Utilitaire interne – inférence du type BigQuery
# ---------------------------------------------------------------------------

def _bq_type(value) -> str:
    """Infère le type de paramètre BigQuery à partir de la valeur Python."""
    if isinstance(value, bool):     return "BOOL"
    if isinstance(value, int):      return "INT64"
    if isinstance(value, float):    return "FLOAT64"
    if isinstance(value, datetime): return "TIMESTAMP"
    if isinstance(value, date):     return "DATE"
    return "STRING"


# ---------------------------------------------------------------------------
# INSERT TEAMS
# ---------------------------------------------------------------------------

def insert_team(team_id: str, name: str):
    execute(
        f"""
        INSERT INTO {_full_table('teams')}
        (id, name, created_at)
        VALUES (@id, @name, CURRENT_TIMESTAMP())
        """,
        {
            "id":   team_id,
            "name": name,
        }
    )


# ---------------------------------------------------------------------------
# INSERT AGENTS
# ---------------------------------------------------------------------------

def insert_agent(agent_id: str, team_id: str, full_name: str, initials: str = None, email: str = None):
    execute(
        f"""
        INSERT INTO {_full_table('agents')}
        (id, team_id, full_name, initials, email, created_at)
        VALUES (@id, @team_id, @full_name, @initials, @email, CURRENT_TIMESTAMP())
        """,
        {
            "id":       agent_id,
            "team_id":  team_id,
            "full_name": full_name,
            "initials": initials or "",
            "email":    email or "",
        }
    )