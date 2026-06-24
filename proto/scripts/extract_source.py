"""
Étapes 1-2 du pipeline d'ingestion — extraction et normalisation d'une source.

Transforme une source (tableur .xlsx/.csv/.tsv ou PDF) en une liste normalisée
d'exigences (colonnes « Référence », « Critère ») prête pour scripts/ingest_framework.py.

Usage :
    # Tableur / CSV
    python scripts/extract_source.py --source source.xlsx --out criteria.csv \
        [--criterion-col "Exigence"] [--reference-col "N°"]

    # PDF (heuristique de numérotation, ou --llm pour une extraction assistée OpenAI)
    python scripts/extract_source.py --source norme.pdf --out criteria.csv [--llm]

Sortie : criteria.csv (Référence, Critère). DRY-RUN : aucune écriture en base.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

PROTO = Path(__file__).resolve().parent.parent
load_dotenv(PROTO / ".env")

# motif « 1.2 », « 1.2.3 » ou « 12. » en début de ligne
NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+(.{8,})$")


def from_spreadsheet(path: Path, crit_col: str | None, ref_col: str | None) -> list[dict]:
    import pandas as pd

    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    else:
        sep = "\t" if path.suffix.lower() == ".tsv" else ","
        df = pd.read_csv(path, dtype=str, sep=sep)
    df = df.fillna("")
    cols = {c.lower().strip(): c for c in df.columns}

    def pick(name, *aliases):
        if name and name in df.columns:
            return name
        for a in aliases:
            if a in cols:
                return cols[a]
        return None

    c_crit = pick(crit_col, "critère", "critere", "exigence", "label", "intitulé", "intitule")
    c_ref = pick(ref_col, "référence", "reference", "ref", "n°", "no", "code")
    if not c_crit:
        # repli : première colonne textuelle « longue »
        c_crit = max(df.columns, key=lambda c: df[c].astype(str).str.len().mean())
    rows = []
    for _, r in df.iterrows():
        label = str(r[c_crit]).strip()
        if not label:
            continue
        rows.append({"reference": (str(r[c_ref]).strip() if c_ref else "") or None, "criterion": label})
    return rows


def from_pdf_heuristic(path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    rows = []
    for line in text.splitlines():
        m = NUM_RE.match(line)
        if m:
            rows.append({"reference": m.group(1), "criterion": m.group(2).strip()})
    return rows


def from_pdf_llm(path: Path) -> list[dict]:
    from openai import OpenAI
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    text = text[:16000]  # borne de coût pour le proto
    client = OpenAI()
    prompt = (
        "Extrais les exigences/critères de ce référentiel. Pour chaque exigence, donne sa "
        "référence (numéro de clause si présent, sinon null) et son intitulé complet.\n"
        "Réponds en JSON strict : {\"items\": [{\"reference\": \"...\"|null, \"criterion\": \"...\"}]}\n\n"
        f"TEXTE :\n{text}"
    )
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    return [
        {"reference": (it.get("reference") or None), "criterion": (it.get("criterion") or "").strip()}
        for it in data.get("items", [])
        if (it.get("criterion") or "").strip()
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", default="criteria.csv")
    ap.add_argument("--criterion-col", default=None)
    ap.add_argument("--reference-col", default=None)
    ap.add_argument("--llm", action="store_true", help="PDF : extraction assistée OpenAI")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.is_absolute():
        src = PROTO / args.source
    if not src.exists():
        print(f"ERREUR : source introuvable : {src}", file=sys.stderr)
        return 1

    ext = src.suffix.lower()
    if ext in {".csv", ".tsv", ".xlsx", ".xls"}:
        rows = from_spreadsheet(src, args.criterion_col, args.reference_col)
    elif ext == ".pdf":
        if args.llm:
            if not os.environ.get("OPENAI_API_KEY"):
                print("ERREUR : --llm demandé mais OPENAI_API_KEY absent", file=sys.stderr)
                return 1
            rows = from_pdf_llm(src)
        else:
            rows = from_pdf_heuristic(src)
            if not rows:
                print("Aucune exigence détectée par heuristique. Réessaie avec --llm.", file=sys.stderr)
    else:
        print(f"ERREUR : format non supporté : {ext}", file=sys.stderr)
        return 1

    out = PROTO / args.out if not Path(args.out).is_absolute() else Path(args.out)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Référence", "Critère"])
        for r in rows:
            w.writerow([r["reference"] or "", r["criterion"]])
    print(f"✓ {len(rows)} exigences extraites → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
