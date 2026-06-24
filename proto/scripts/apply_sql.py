"""
Applique un fichier SQL sur la base via DATABASE_URL (connexion directe).

Usage :
    python scripts/apply_sql.py db/schema.sql
    python scripts/apply_sql.py db/functions.sql
"""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)


def main(sql_path: str) -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERREUR : DATABASE_URL absent de .env", file=sys.stderr)
        return 1

    path = Path(sql_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / sql_path
    sql = path.read_text(encoding="utf-8")

    with psycopg.connect(database_url, connect_timeout=15, autocommit=True) as conn:
        conn.execute(sql)  # psycopg3 : multi-statements via le protocole simple
    print(f"✓ Appliqué : {path.name}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python scripts/apply_sql.py <fichier.sql>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
