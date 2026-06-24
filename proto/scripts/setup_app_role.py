"""
Provisionne le rôle applicatif `frameko_app` (créé par db/03_auth_rls.sql) :
- lui attribue un mot de passe et l'autorise à se connecter (LOGIN) ;
- écrit APP_DATABASE_URL dans .env (connexion à moindre privilège, soumise à RLS).

À lancer une fois, après db/03_auth_rls.sql. Idempotent : régénère le mot de passe.

Usage :
    python scripts/setup_app_role.py
"""

import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
ENV = PROTO / ".env"
load_dotenv(ENV)


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERREUR : DATABASE_URL absent de .env", file=sys.stderr)
        return 1

    pw = secrets.token_urlsafe(24)
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("select 1 from pg_roles where rolname = 'frameko_app'").fetchone()
        if not row:
            print("ERREUR : rôle frameko_app absent — applique d'abord db/03_auth_rls.sql", file=sys.stderr)
            return 1
        conn.execute(f"alter role frameko_app login password '{pw}'")

    parts = urlsplit(url)
    hostport = parts.netloc.split("@")[-1]
    app_url = urlunsplit((parts.scheme, f"frameko_app:{pw}@{hostport}", parts.path, parts.query, parts.fragment))

    lines = ENV.read_text(encoding="utf-8").splitlines()
    lines = [l for l in lines if not l.startswith("APP_DATABASE_URL=")]
    lines.append("APP_DATABASE_URL=" + app_url)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("✓ Rôle frameko_app : LOGIN activé, mot de passe régénéré.")
    print("✓ APP_DATABASE_URL écrit dans .env (non versionné).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
