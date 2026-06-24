"""
Ingestion d'un référentiel — logique partagée (CCCEV-isation).

Trois étapes, génériques (indépendantes du domaine), réutilisées par l'UI web
(wizard) et exploitables en CLI :

  1. extract_from_path(path)        source (.xlsx/.csv/.tsv/.pdf) → exigences
  2. propose(criteria)              rattachement au socle commun (candidats + degré suggéré)
  3. apply_framework(framework, …)  insertion validée (framework + critères + embeddings)

Aucune écriture en base avant apply_framework ; les étapes 1-2 sont en lecture seule.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import db
from .embeddings import embed_one, embed_texts, to_pgvector

DEGREES = ["equivautA", "plusStrictQue", "plusLargeQue", "rapprocheDe"]
_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(.{8,})$")


# ── 1. Extraction ────────────────────────────────────────────────────────────

def extract_from_path(path: Path) -> list[dict]:
    """Détecte le format et renvoie [{reference, criterion}]. Lecture seule."""
    ext = path.suffix.lower()
    if ext in {".xlsx", ".xls", ".csv", ".tsv"}:
        return _from_spreadsheet(path)
    if ext == ".pdf":
        return _from_pdf(path)
    raise ValueError(f"Format non supporté : {ext} (attendu .xlsx/.csv/.tsv/.pdf)")


def _from_spreadsheet(path: Path) -> list[dict]:
    import pandas as pd

    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        df = pd.read_csv(path, dtype=str, sep=sep)
    df = df.fillna("")
    cols = {c.lower().strip(): c for c in df.columns}

    def pick(*aliases):
        for a in aliases:
            if a in cols:
                return cols[a]
        return None

    c_crit = pick("critère", "critere", "exigence", "label", "intitulé", "intitule")
    c_ref = pick("référence", "reference", "ref", "n°", "no", "code")
    if not c_crit:
        c_crit = max(df.columns, key=lambda c: df[c].astype(str).str.len().mean())
    rows = []
    for _, r in df.iterrows():
        label = str(r[c_crit]).strip()
        if not label:
            continue
        rows.append({"reference": (str(r[c_ref]).strip() if c_ref else "") or None, "criterion": label})
    return rows


def _from_pdf(path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    rows = []
    for line in text.splitlines():
        m = _NUM_RE.match(line)
        if m:
            rows.append({"reference": m.group(1), "criterion": m.group(2).strip()})
    return rows


# ── 2. Rattachement au socle commun ──────────────────────────────────────────

def propose(criteria: list[dict], limit: int | None = None) -> list[dict]:
    """Pour chaque exigence, propose le rattachement : candidats (critères communs
    proches), précédents (exigences déjà qualifiées) et un degré suggéré dérivé du
    précédent le plus proche. Aucune écriture en base."""
    items = criteria[:limit] if limit else criteria
    labels = [c["criterion"] for c in items]
    if not labels:
        return []
    vectors = embed_texts(labels)
    out = []
    for item, vec in zip(items, vectors):
        lit = to_pgvector(vec)
        candidates = db.match_common(lit, k=5)
        precedents = db.nearest_fc(lit, k=3)
        top = candidates[0] if candidates else None
        # degré suggéré : celui du précédent le plus proche (sinon le plus prudent)
        sug_degree = precedents[0]["degree"] if precedents else "rapprocheDe"
        out.append({
            "reference": item.get("reference"),
            "criterion": item["criterion"],
            "candidates": [
                {"common_code": c["code"], "label": c["label_fr"],
                 "theme_slug": c["theme_slug"], "similarity": round(float(c["similarity"]), 3)}
                for c in candidates
            ],
            "precedents": [
                {"framework_slug": p["framework_slug"], "reference": p["reference"],
                 "label": p["label"], "common_code": p["common_code"],
                 "degree": p["degree"], "similarity": round(float(p["similarity"]), 3)}
                for p in precedents
            ],
            "suggested": {
                "common_code": top["code"] if top else None,
                "degree": sug_degree,
                "confidence": round(float(top["similarity"]), 3) if top else 0.0,
            },
        })
    return out


# ── 3. Insertion validée ─────────────────────────────────────────────────────

def validate(framework: dict, proposals: list[dict]) -> list[str]:
    """Contrôle les garde-fous avant écriture. Renvoie la liste des erreurs."""
    errors = []
    if not framework.get("slug"):
        errors.append("framework.slug requis")
    if not framework.get("title"):
        errors.append("framework.title requis")
    if not proposals:
        errors.append("aucune proposition")
    known = {r["code"] for r in db.query("select code from common_criterion")}
    for i, p in enumerate(proposals, 1):
        sug = p.get("suggested") or {}
        if not sug.get("common_code"):
            errors.append(f"#{i} ({p.get('reference')}): critère commun manquant")
        elif sug["common_code"] not in known:
            errors.append(f"#{i} ({p.get('reference')}): critère commun inconnu ({sug['common_code']})")
        if sug.get("degree") not in DEGREES:
            errors.append(f"#{i} ({p.get('reference')}): degré invalide ({sug.get('degree')!r})")
    return errors


def apply_framework(framework: dict, proposals: list[dict], replace: bool = False) -> dict:
    """Insère le référentiel validé (framework + critères + rattachements + embeddings)
    dans une transaction. Lève ValueError si validation échoue ou slug déjà présent."""
    errors = validate(framework, proposals)
    if errors:
        raise ValueError("; ".join(errors[:8]))

    slug = framework["slug"]
    labels = [p["criterion"] for p in proposals]
    vectors = embed_texts(labels)

    with db._admin().connection() as conn:
        with conn.transaction():
            cur = conn.cursor()
            cc = {}  # code → (id, theme_slug) des critères communs connus
            for row in cur.execute("select code, id, theme_slug from common_criterion").fetchall():
                cc[row["code"]] = (row["id"], row["theme_slug"])

            exists = cur.execute("select 1 as ok from framework where slug = %s", (slug,)).fetchone()
            if exists and not replace:
                raise ValueError(f"le référentiel '{slug}' existe déjà (utiliser replace)")
            if exists:
                cur.execute("delete from framework_criterion where framework_slug = %s", (slug,))
                cur.execute("delete from framework where slug = %s", (slug,))

            cur.execute(
                "insert into framework (slug, title, publisher, version, coverage, status)"
                " values (%s, %s, %s, %s, %s, %s)",
                (slug, framework["title"], framework.get("publisher"),
                 framework.get("version"), framework.get("coverage"), framework.get("status", "actif")),
            )
            rows = []
            for p, vec in zip(proposals, vectors):
                sug = p["suggested"]
                cc_id, theme_slug = cc[sug["common_code"]]
                rows.append((slug, p.get("reference"), p["criterion"], theme_slug,
                             p.get("level"), sug["degree"], cc_id, to_pgvector(vec)))
            cur.executemany(
                "insert into framework_criterion"
                " (framework_slug, reference, label, theme_slug, level, degree, common_criterion_id, embedding)"
                " values (%s, %s, %s, %s, %s, %s, %s, %s::vector)",
                rows,
            )
    return {"slug": slug, "inserted": len(proposals)}
