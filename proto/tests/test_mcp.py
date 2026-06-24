"""Tests des outils du serveur MCP (fastmcp, client en mémoire)."""

import asyncio

from fastmcp import Client

from mcp_server.server import mcp

EXPECTED_TOOLS = {
    "list_frameworks", "get_framework", "search_requirements", "nearest_requirements",
    "propose_mapping", "compare_frameworks", "start_assessment", "answer_assessment",
    "get_assessment_result",
}


def _run(coro):
    return asyncio.run(coro)


def test_tools_exposed(db):
    async def go():
        async with Client(mcp) as c:
            return {t.name for t in await c.list_tools()}
    assert _run(go()) == EXPECTED_TOOLS


def test_s1_frameworks(db):
    async def go():
        async with Client(mcp) as c:
            fws = (await c.call_tool("list_frameworks", {})).data
            fw = (await c.call_tool("get_framework", {"slug": "florverde"})).data
            return fws, fw
    fws, fw = _run(go())
    assert len(fws) == 9
    assert fw["title"].startswith("Florverde")
    assert len(fw["criteres"]) == 225


def test_s2_search_and_propose(db):
    async def go():
        async with Client(mcp) as c:
            sr = (await c.call_tool("search_requirements", {"query": "économie de l'eau"})).data
            srf = (await c.call_tool("search_requirements",
                                     {"query": "eau", "framework": "planetproof"})).data
            pm = (await c.call_tool("propose_mapping",
                                    {"criterion_text": "formation des opérateurs pesticides"})).data
            return sr, srf, pm
    sr, srf, pm = _run(go())
    assert sr["common_criteria"]
    assert all(r["framework_slug"] == "planetproof" for r in srf["framework_criteria"])
    assert pm["candidates"] and "degrees" in pm


def test_s2_compare(db):
    async def go():
        async with Client(mcp) as c:
            return (await c.call_tool("compare_frameworks",
                                      {"a": "florverde", "b": "planetproof"})).data
    cmp = _run(go())
    assert cmp["summary"]["communs_partages"] >= 1


def test_s3_assessment_requires_org(db, monkeypatch):
    # sans FRAMEKO_ORG_TOKEN → refus
    monkeypatch.delenv("FRAMEKO_ORG_TOKEN", raising=False)

    async def go():
        async with Client(mcp) as c:
            return (await c.call_tool("start_assessment", {"framework": "florverde"})).data
    assert "error" in _run(go())


def test_s3_assessment_cycle(db, org, monkeypatch):
    monkeypatch.setenv("FRAMEKO_ORG_TOKEN", org["token"])
    # libellé d'un critère commun réellement couvert par le référentiel
    with db.cursor() as cur:
        cur.execute(
            """select distinct cc.label_fr from framework_criterion fc
               join common_criterion cc on cc.id = fc.common_criterion_id
               where fc.framework_slug = 'charte-qualite-fleurs' limit 1"""
        )
        label = cur.fetchone()["label_fr"]

    async def go():
        async with Client(mcp) as c:
            aid = (await c.call_tool("start_assessment", {"framework": "charte-qualite-fleurs"})).data["assessment_id"]
            ans = (await c.call_tool("answer_assessment", {
                "assessment_id": aid, "common_criterion_label": label, "status": "conforme"})).data
            res = (await c.call_tool("get_assessment_result", {"assessment_id": aid})).data
            return aid, ans, res

    aid, ans, res = _run(go())
    assert ans.get("ok") is True
    assert res["conforme"] == 1
    assert res["coverage_rate"] >= 0


def test_unknown_slug(db):
    async def go():
        async with Client(mcp) as c:
            return (await c.call_tool("get_framework", {"slug": "inexistant"})).data
    assert "error" in _run(go())
