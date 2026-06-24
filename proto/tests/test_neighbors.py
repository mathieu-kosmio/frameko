"""Tests du voisinage, de la comparaison au niveau critère, et de la CCCEV-isation
(module mcp_server.ingest : propose → apply → voisinage du nouveau référentiel)."""

import pytest

from mcp_server import db as appdb
from mcp_server import ingest


def test_framework_neighbors(db):
    with db.cursor() as cur:
        cur.execute("select count(*) as n from framework")
        total = cur.fetchone()["n"]
        cur.execute("select * from framework_neighbors('florverde')")
        rows = cur.fetchall()
    # tous les autres référentiels (total - le pivot), triés par nb partagé
    assert len(rows) == total - 1
    shared = [r["n_shared"] for r in rows]
    assert shared == sorted(shared, reverse=True)
    # florecuador est le plus proche de florverde
    assert rows[0]["slug"] == "florecuador" and rows[0]["n_shared"] >= 1


def test_framework_pair_detail(db):
    with db.cursor() as cur:
        cur.execute("select * from framework_pair_detail('florverde', 'plante-bleue')")
        rows = cur.fetchall()
    assert len(rows) >= 1
    r = rows[0]
    # chaque critère commun partagé porte des exigences réelles des deux côtés
    assert r["a_items"] and r["b_items"]
    valid = {"equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"}
    assert r["a_items"][0]["degree"] in valid
    assert "label" in r["a_items"][0]


def test_framework_criteria(db):
    """Parcours d'un référentiel : tous ses critères, avec thème et rattachement."""
    rows = appdb.framework_criteria("charte-qualite-fleurs")
    assert len(rows) == 17  # nb de critères de ce référentiel
    valid = {"equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"}
    for r in rows:
        assert r["label"] and r["common_code"] and r["degree"] in valid
    # au moins un critère porte un thème (jointure catégorie/thème OK)
    assert any(r["theme_label"] for r in rows)


def test_criterion_evidence_linked(db):
    """Les critères FlorEcuador sont reliés à des types de preuves (CCCEV EvidenceType)."""
    # le catalogue de types de preuves est seedé
    types = {r["slug"] for r in appdb.query("select slug from evidence_type")}
    assert {"registre", "certificat", "document", "inspection"} <= types
    rows = appdb.framework_criteria("florecuador")
    linked = [r for r in rows if r["evidence_types"]]
    assert len(linked) >= 150  # la grande majorité des 195 critères ont une preuve
    sample = linked[0]
    assert sample["evidence_detail"]  # texte du moyen de vérification
    assert all("slug" in e and "label" in e for e in sample["evidence_types"])


def test_ingest_propose():
    crit = [{"reference": "1.1", "criterion": "Maintien de la diversité biologique des forêts"}]
    props = ingest.propose(crit)
    assert len(props) == 1
    p = props[0]
    assert p["candidates"] and p["suggested"]["common_code"] == p["candidates"][0]["common_code"]
    assert p["suggested"]["degree"] in {"equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"}


def test_ingest_apply_and_neighbors(db):
    """CCCEV-iser un référentiel jetable, vérifier qu'il rejoint le voisinage, puis nettoyer."""
    slug = "_test_ingest_neighbors"
    fw = {"slug": slug, "title": "Référentiel de test", "publisher": "test"}
    props = [
        {"reference": "1.1", "criterion": "Diversité biologique des écosystèmes",
         "suggested": {"common_code": "c-041", "degree": "equivautA"}},
        {"reference": "4.2", "criterion": "Traçabilité de la chaîne de contrôle",
         "suggested": {"common_code": "c-050", "degree": "rapprocheDe"}},
    ]
    try:
        res = ingest.apply_framework(fw, props, replace=True)
        assert res["inserted"] == 2
        # le nouveau référentiel partage c-041 et c-050 avec les autres
        neighbors = appdb.neighbors(slug)
        assert any(n["n_shared"] >= 1 for n in neighbors)
    finally:
        with db.cursor() as cur:
            cur.execute("delete from framework_criterion where framework_slug = %s", (slug,))
            cur.execute("delete from framework where slug = %s", (slug,))
    assert not appdb.framework_exists(slug)


def test_ingest_apply_rejects_invalid_degree(db):
    """Garde-fou : apply refuse un degré absent/invalide (validation requise)."""
    fw = {"slug": "_test_bad", "title": "X"}
    props = [{"reference": "1", "criterion": "y", "suggested": {"common_code": "c-041", "degree": None}}]
    with pytest.raises(ValueError):
        ingest.apply_framework(fw, props, replace=True)
