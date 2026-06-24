"""
Crée une organisation et émet son jeton d'accès (affiché UNE seule fois).

Usage :
    python scripts/create_org.py --slug acme --name "ACME Fleurs"
"""

import argparse
import secrets
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")
sys.path.insert(0, str(PROTO))

import os  # noqa: E402

from mcp_server.auth import hash_token  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()

    token = secrets.token_urlsafe(24)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        try:
            conn.execute(
                "insert into org (slug, name, token_hash) values (%s, %s, %s)",
                (args.slug, args.name, hash_token(token)),
            )
        except psycopg.errors.UniqueViolation:
            print(f"ERREUR : le slug '{args.slug}' existe déjà.", file=sys.stderr)
            return 1

    print(f"✓ Organisation '{args.name}' ({args.slug}) créée.")
    print(f"\n  JETON (à conserver, non récupérable) :\n    {token}\n")
    print("  Web  : se connecter avec ce jeton dans l'onglet Auto-évaluation.")
    print("  MCP  : exporter FRAMEKO_ORG_TOKEN=<jeton> avant de lancer le serveur.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
