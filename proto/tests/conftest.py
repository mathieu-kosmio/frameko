"""Fixtures partagées — connexion à la base et chargement des scripts."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")
sys.path.insert(0, str(PROTO))

DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session")
def db():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL absent de .env")
    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row)
    # garde-fou : la base doit être chargée
    with conn.cursor() as cur:
        cur.execute("select count(*) as n from framework")
        if cur.fetchone()["n"] == 0:
            pytest.skip("base vide — exécuter scripts/load_data.py + build_embeddings.py")
    yield conn
    conn.close()


def load_script(name: str):
    """Charge un script de scripts/ comme module (ils ne forment pas un package)."""
    spec = importlib.util.spec_from_file_location(name, PROTO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
