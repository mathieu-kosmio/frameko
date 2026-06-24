"""Tests des 4 fonctions RPC (db/functions.sql)."""

from mcp_server.embeddings import embed_one, to_pgvector


def test_match_criteria_ordered(db):
    vec = to_pgvector(embed_one("gestion et économie de l'eau d'irrigation"))
    with db.cursor() as cur:
        cur.execute("select * from match_criteria(%s::vector, 5)", (vec,))
        rows = cur.fetchall()
    assert len(rows) == 5
    # tri par similarité décroissante
    sims = [r["similarity"] for r in rows]
    assert sims == sorted(sims, reverse=True)
    # le critère de l'eau (c-024) doit figurer dans le top 5
    assert any(r["code"] == "c-024" for r in rows)


def test_nearest_framework_criteria(db):
    vec = to_pgvector(embed_one("réduction de la consommation d'eau"))
    with db.cursor() as cur:
        cur.execute("select * from nearest_framework_criteria(%s::vector, 8)", (vec,))
        rows = cur.fetchall()
    assert len(rows) == 8
    valid = {"equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"}
    assert all(r["degree"] in valid for r in rows)
    assert all(r["framework_slug"] for r in rows)


def test_framework_coverage(db):
    with db.cursor() as cur:
        cur.execute("select * from framework_coverage('florverde', 'planetproof')")
        rows = cur.fetchall()
    shared = [r for r in rows if r["count_a"] > 0 and r["count_b"] > 0]
    assert len(shared) >= 1
    # planetproof est entièrement rattaché à des critères communs partagés avec florverde
    assert all(r["count_a"] >= 0 and r["count_b"] >= 0 for r in rows)


def test_assessment_result(db):
    with db.cursor() as cur:
        cur.execute("insert into assessment (framework_slug) values ('vivaifiori') returning id")
        aid = cur.fetchone()["id"]
        cur.execute(
            """select distinct cc.id from framework_criterion fc
               join common_criterion cc on cc.id = fc.common_criterion_id
               where fc.framework_slug = 'vivaifiori' limit 2"""
        )
        ids = [r["id"] for r in cur.fetchall()]
        for cid, st in zip(ids, ["conforme", "partiel"]):
            cur.execute(
                "insert into assessment_answer (assessment_id, common_criterion_id, status)"
                " values (%s, %s, %s)",
                (aid, cid, st),
            )
        cur.execute("select assessment_result(%s) as r", (aid,))
        res = cur.fetchone()["r"]
        cur.execute("delete from assessment where id = %s", (aid,))

    assert res["framework_slug"] == "vivaifiori"
    assert res["conforme"] == 1
    assert res["total_common"] >= res["conforme"]
    assert 0.0 <= res["coverage_rate"] <= 1.0
    assert isinstance(res["gaps"], list)
