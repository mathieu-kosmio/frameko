"""
Tâche 4 — Calcul et stockage des embeddings.

Calcule l'embedding du libellé de chaque critère commun et de chaque critère de
référentiel avec le modèle local (384 dim), et le stocke dans la colonne `embedding`.

Usage :
    cd proto
    python scripts/build_embeddings.py
"""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")
sys.path.insert(0, str(PROTO))

from mcp_server.embeddings import EMBEDDING_DIM, embed_texts, to_pgvector  # noqa: E402

BATCH = 128


def embed_table(conn: psycopg.Connection, table: str, label_col: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"select id, {label_col} from {table} where embedding is null order by id")
        rows = cur.fetchall()

    total = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        ids = [r[0] for r in chunk]
        labels = [r[1] for r in chunk]
        vectors = embed_texts(labels)
        with conn.cursor() as cur:
            cur.executemany(
                f"update {table} set embedding = %s::vector where id = %s",
                [(to_pgvector(v), cid) for cid, v in zip(ids, vectors)],
            )
        conn.commit()
        total += len(chunk)
        print(f"  {table}: {total}/{len(rows)}")
    return total


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERREUR : DATABASE_URL absent de .env", file=sys.stderr)
        return 1

    print(f"Modèle d'embedding ({EMBEDDING_DIM} dim) — premier appel : téléchargement du modèle…")
    with psycopg.connect(database_url, autocommit=False) as conn:
        embed_table(conn, "common_criterion", "label_fr")
        embed_table(conn, "framework_criterion", "label")

        with conn.cursor() as cur:
            cur.execute("select count(*) from common_criterion where embedding is null")
            cc_null = cur.fetchone()[0]
            cur.execute("select count(*) from framework_criterion where embedding is null")
            fc_null = cur.fetchone()[0]

    print(f"\nEmbeddings nuls — common_criterion: {cc_null}, framework_criterion: {fc_null}")
    if cc_null == 0 and fc_null == 0:
        print("✓ Aucun embedding nul.")
        return 0
    print("✗ Des embeddings sont nuls.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
