# Frameko — Prototype

API REST + serveur MCP pour la plateforme d'agrégation de référentiels de certification.

## Stack

- **FastAPI** — API REST versionnée (`/v1`)
- **Supabase** — Postgres + pgvector + Auth + RLS
- **MCP** — serveur pour agents IA (Claude, etc.)
- **Python 3.11+**

## Installation

```bash
cd proto
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # renseigner les variables Supabase
```

## Base de données

```bash
# Exécuter la migration dans Supabase SQL Editor ou via psql
psql $DATABASE_URL -f migrations/001_initial_schema.sql

# Charger l'ontologie existante
python scripts/seed_ontology.py --ttl ../ONTOLOGIE/floriscore-referentiels.ttl
```

## Lancer l'API

```bash
frameko-api
# ou
uvicorn frameko.api.main:app --reload
```

API disponible sur `http://localhost:8000` — docs Swagger sur `/docs`.

## Lancer le serveur MCP

```bash
frameko-mcp
```

Le serveur MCP tourne en stdio et peut être branché à Claude via la config MCP standard.

## Services exposés

| Service | Description | Endpoints |
|---|---|---|
| **S1** | Référentiels et exigences | `GET /v1/frameworks`, `GET /v1/criteria/{id}` |
| **S2** | Proximité et analyse croisée | `POST /v1/match`, `GET /v1/frameworks/{a}/compare/{b}` |
| **S3** | Auto-évaluation de conformité | `POST /v1/assessments`, `GET /v1/assessments/{id}/result` |
| Export | Turtle, CSV | `GET /v1/export?format=csv\|turtle` |
| Ingestion | Dépôt et suivi de sources | `POST /v1/ingestion-jobs` |

## Tests

```bash
pytest
```

## Structure

```
src/frameko/
  config.py           Variables d'environnement
  api/
    main.py           Point d'entrée FastAPI
    models.py         Schémas Pydantic
    routes/
      frameworks.py   S1 — référentiels
      criteria.py     S1 — critères communs
      match.py        S2 — proximité vectorielle
      assessments.py  S3 — auto-évaluation
      ingestion.py    Pipeline d'ingestion
      export.py       Export Turtle / CSV
  db/
    client.py         Pool Postgres + client Supabase
  mcp/
    server.py         Serveur MCP (7 outils)
  services/
    embeddings.py     Service d'embedding
migrations/
  001_initial_schema.sql
scripts/
  seed_ontology.py    Charge le Turtle dans Postgres
```
