"""Test de l'extraction depuis un tableur/CSV (déterministe, sans réseau)."""

from pathlib import Path

from conftest import load_script


def test_extract_csv_detects_columns(tmp_path):
    extract = load_script("extract_source")
    csv_path = tmp_path / "src.csv"
    csv_path.write_text(
        "Référence,Exigence\n"
        "1.1,L'exploitation tient un registre d'irrigation.\n"
        "2.0,Formation annuelle des opérateurs.\n",
        encoding="utf-8",
    )
    rows = extract.from_spreadsheet(csv_path, None, None)
    assert len(rows) == 2
    assert rows[0]["reference"] == "1.1"
    assert "registre" in rows[0]["criterion"]


def test_extract_pdf_heuristic_regex():
    extract = load_script("extract_source")
    # le motif de numérotation détecte « N.N intitulé »
    m = extract.NUM_RE.match("1.2 Les opérateurs reçoivent une formation annuelle certifiée.")
    assert m and m.group(1) == "1.2"
    assert m.group(2).startswith("Les opérateurs")
