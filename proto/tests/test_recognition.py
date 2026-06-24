"""Tests de la couche de reconnaissance / équivalence (FSI)."""

from mcp_server import db as appdb


def test_recognition_scheme_present(db):
    with db.cursor() as cur:
        cur.execute("select * from recognition_scheme where slug = 'fsi'")
        scheme = cur.fetchone()
    assert scheme and "Floriculture" in scheme["name"]


def test_recognition_basket_pillars(db):
    with db.cursor() as cur:
        cur.execute("select distinct pillar from recognition where scheme_slug = 'fsi' order by pillar")
        pillars = [r["pillar"] for r in cur.fetchall()]
    assert pillars == ["Environmental", "GAP", "Social"]


def test_recognition_links_to_base(db):
    """Les standards reconnus pointant vers un slug existent réellement en base."""
    rows = appdb.recognitions("fsi")
    linked = [r for r in rows if r["framework_slug"]]
    assert len(linked) >= 8  # au moins 8 de nos référentiels sont reconnus par FSI
    for r in linked:
        assert r["framework_title"], f"slug {r['framework_slug']} sans titre (FK cassée ?)"


def test_framework_equivalences(db):
    """florverde (reconnu sur les 3 piliers) est équivalent à plusieurs autres."""
    eq = appdb.framework_equivalences("florverde")
    slugs = {e["slug"] for e in eq}
    assert "mps-gap" in slugs and "rainforest-alliance" in slugs
    # mps-gap partage les piliers GAP et Environmental avec florverde
    mps = next(e for e in eq if e["slug"] == "mps-gap")
    assert "GAP" in mps["shared_pillars"] and "Environmental" in mps["shared_pillars"]
    # un référentiel hors panier FSI n'a pas d'équivalence
    assert appdb.framework_equivalences("plante-bleue") == []
