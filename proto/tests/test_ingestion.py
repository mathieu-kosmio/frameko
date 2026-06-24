"""Tests de la boucle d'ingestion : apply (insertion) + garde-fous."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parent.parent
APPLY = PROTO / "scripts" / "apply_ingestion.py"
SLUG = "pytest-tmp-fw"


@pytest.fixture
def cleanup_fw(db):
    yield
    with db.cursor() as cur:
        cur.execute("delete from framework_criterion where framework_slug = %s", (SLUG,))
        cur.execute("delete from framework where slug = %s", (SLUG,))


def _write(tmp_path, proposals) -> Path:
    p = tmp_path / "proposals.json"
    p.write_text(json.dumps({
        "framework": {"slug": SLUG, "title": "Pytest TMP"},
        "proposals": proposals,
    }, ensure_ascii=False), encoding="utf-8")
    return p


def _apply(path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(APPLY), "--proposals", str(path), *extra],
        capture_output=True, text=True,
    )


def test_apply_rejects_missing_degree(db, tmp_path):
    path = _write(tmp_path, [
        {"reference": "1", "criterion": "Exigence sans degré.", "suggested": {"common_code": "c-024", "degree": None}},
    ])
    r = _apply(path)
    assert r.returncode == 1
    assert "VALIDATION" in (r.stdout + r.stderr)


def test_apply_rejects_unknown_code(db, tmp_path):
    path = _write(tmp_path, [
        {"reference": "1", "criterion": "Exigence.", "suggested": {"common_code": "c-999", "degree": "equivautA"}},
    ])
    r = _apply(path)
    assert r.returncode == 1
    assert "inconnu" in (r.stdout + r.stderr).lower()


def test_apply_inserts_and_links(db, tmp_path, cleanup_fw):
    path = _write(tmp_path, [
        {"reference": "1.1", "criterion": "Registre de consommation d'eau d'irrigation.",
         "suggested": {"common_code": "c-024", "degree": "plusStrictQue"}},
        {"reference": "3.5", "criterion": "Plan de gestion des déchets dangereux.",
         "suggested": {"common_code": "c-036", "degree": "equivautA"}},
    ])
    r = _apply(path)
    assert r.returncode == 0, r.stdout + r.stderr

    with db.cursor() as cur:
        cur.execute("select count(*) as n from framework where slug = %s", (SLUG,))
        assert cur.fetchone()["n"] == 1
        cur.execute(
            "select count(*) as n, count(embedding) as emb,"
            " count(common_criterion_id) as cc from framework_criterion where framework_slug = %s",
            (SLUG,),
        )
        row = cur.fetchone()
        assert row["n"] == 2          # 2 critères insérés
        assert row["emb"] == 2        # embeddings calculés
        assert row["cc"] == 2         # tous rattachés

    # idempotence : sans --replace → refus
    assert _apply(path).returncode == 1
    # avec --replace → OK
    assert _apply(path, "--replace").returncode == 0
