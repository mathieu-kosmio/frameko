"""Tests d'authentification et d'isolation par organisation (RLS, rôle frameko_app)."""

import os
import secrets

import pytest

from mcp_server import auth, db


@pytest.fixture
def two_orgs(db):
    from mcp_server.auth import hash_token

    made = []
    for n in ("a", "b"):
        tok = secrets.token_urlsafe(16)
        slug = f"pytest-{n}-" + secrets.token_hex(3)
        with db.cursor() as cur:
            cur.execute(
                "insert into org (slug,name,token_hash) values (%s,%s,%s) returning id::text as id",
                (slug, slug, hash_token(tok)),
            )
            made.append({"id": cur.fetchone()["id"], "slug": slug, "token": tok})
    yield made
    with db.cursor() as cur:
        for o in made:
            cur.execute("delete from org where id = %s", (o["id"],))


def test_resolve_org(org):
    found = auth.resolve_org(org["token"])
    assert found and found["slug"] == org["slug"]
    assert auth.resolve_org("mauvais-jeton") is None
    assert auth.resolve_org("") is None


def test_bearer_token_parsing(monkeypatch):
    """Multi-tenant : jeton lu dans le header Authorization (HTTP), sinon repli env."""
    from mcp_server import server

    monkeypatch.setattr(server, "get_http_headers", lambda **k: {"authorization": "Bearer abc123"})
    assert server._bearer_token() == "abc123"

    monkeypatch.setattr(server, "get_http_headers", lambda **k: {})
    monkeypatch.setenv("FRAMEKO_ORG_TOKEN", "envtok")
    assert server._bearer_token() == "envtok"


@pytest.mark.skipif(not os.environ.get("APP_DATABASE_URL"),
                    reason="APP_DATABASE_URL absent — exécuter scripts/setup_app_role.py")
def test_rls_isolation(two_orgs):
    A, B = two_orgs
    # A crée une évaluation et y répond
    aid = db.start_assessment(A["id"], "florverde")
    cc = db.query_one("select id::text as id from common_criterion limit 1")
    assert db.upsert_answer(A["id"], aid, cc["id"], "conforme", None) is True

    # A voit son résultat
    resA = db.assessment_result(A["id"], aid)
    assert resA and resA["conforme"] == 1

    # B ne voit pas l'évaluation de A
    assert db.assessment_result(B["id"], aid) is None
    # B ne peut pas écrire sur l'évaluation de A (RLS : 0 ligne)
    assert db.upsert_answer(B["id"], aid, cc["id"], "conforme", None) is False

    # B ne voit aucune évaluation via une lecture directe scopée
    with db.org_scope(B["id"]) as c:
        n = c.execute("select count(*) as n from assessment").fetchone()["n"]
    assert n == 0
