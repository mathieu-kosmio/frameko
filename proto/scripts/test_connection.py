"""
Tâche 1 — Test de connexion à Postgres (Supabase).

Lit les identifiants depuis .env (jamais de secret en dur), se connecte via
DATABASE_URL (connexion directe), affiche la version de Postgres et vérifie que
l'extension pgvector peut être créée.

Usage :
    cd proto
    python scripts/test_connection.py
"""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Charge proto/.env quel que soit le répertoire d'appel
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERREUR : DATABASE_URL absent de .env", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(database_url, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()[0]
                print(f"✓ Connexion Postgres réussie")
                print(f"  {version}")

                # Vérifie que l'extension vector peut être créée (idempotent)
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                conn.commit()

                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
                row = cur.fetchone()
                if row:
                    print(f"✓ Extension pgvector active (version {row[0]})")
                else:
                    print("✗ Extension vector introuvable après création", file=sys.stderr)
                    return 1
        return 0
    except Exception as exc:
        print(f"ERREUR de connexion : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
