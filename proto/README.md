# Frameko — proto V1

Squelette technique de la plateforme d'agrégation de référentiels. Charge l'ontologie
(socle commun CCCEV : 9 référentiels horticoles, 51 critères communs, 876 critères qualifiés)
dans **Supabase/Postgres + pgvector**, calcule des **embeddings locaux** (384 dim), et expose
trois services via un **serveur MCP** : recherche sémantique d'exigences, proximité
inter-référentiels, et auto-évaluation de conformité. Une **UI web** légère permet de tester
les mêmes services dans le navigateur.

## Stack

| Élément | Choix |
|---|---|
| Base | Supabase / Postgres 17 + pgvector 0.8 (index HNSW cosinus) |
| Langage | Python 3.13 |
| Embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dim), exécuté via **fastembed** (ONNX, sans torch, aucune clé API) |
| Serveur MCP | **fastmcp** (stdio) |
| UI web | Starlette + page HTML statique |

> **Note embeddings.** Le brief prévoyait `sentence-transformers`. Pour rester léger
> (≈ 50 Mo au lieu de ~2 Go avec torch) le backend par défaut est **fastembed**, qui exécute
> **le même modèle** (vecteurs 384 identiques). Pour utiliser sentence-transformers à la place :
> `pip install sentence-transformers` puis `EMBEDDING_BACKEND=sentence-transformers` dans `.env`.

## Arborescence

```
proto/
  .env                  identifiants Supabase (NON versionné)
  .env.example          modèle de configuration
  requirements.txt
  db/
    schema.sql          tables + pgvector + index HNSW
    functions.sql       4 fonctions RPC (recherche, couverture, évaluation)
  scripts/
    test_connection.py  vérifie la connexion + l'extension vector
    apply_sql.py        applique un fichier .sql via DATABASE_URL
    load_data.py        charge le socle TTL + les 2 CSV
    build_embeddings.py calcule et stocke les embeddings
  mcp_server/
    db.py               accès Postgres
    embeddings.py       service d'embedding (partagé)
    server.py           serveur MCP fastmcp (8 outils)
  web/
    app.py              UI web Starlette
    index.html          interface (recherche, comparaison, auto-évaluation)
```

## Installation

```bash
cd proto
uv venv .venv --python 3.13           # ou : python -m venv .venv
uv pip install --python .venv -r requirements.txt
cp .env.example .env                  # puis renseigner les identifiants Supabase
```

> `requirements.txt` inclut `sentence-transformers` (lourd). Pour une install minimale
> équivalente au proto : `uv pip install --python .venv "psycopg[binary]" python-dotenv rdflib pandas fastembed fastmcp starlette uvicorn`.

## Ordre d'exécution (mise en place de la base)

```bash
# 1. Vérifier la connexion et l'extension pgvector
.venv/bin/python scripts/test_connection.py

# 2. Créer le schéma
.venv/bin/python scripts/apply_sql.py db/schema.sql

# 3. Charger l'ontologie (socle TTL + 9 référentiels + 876 critères)
.venv/bin/python scripts/load_data.py

# 4. Calculer les embeddings (1er appel : téléchargement du modèle ~460 Mo)
.venv/bin/python scripts/build_embeddings.py

# 5. Créer les fonctions RPC
.venv/bin/python scripts/apply_sql.py db/functions.sql
```

Contrôle attendu après l'étape 3 : 7 domaines, 7 catégories, 13 thèmes, 51 critères communs,
9 référentiels, 876 critères, 0 orphelin. Après l'étape 4 : 0 embedding nul.

## Lancer le serveur MCP

```bash
.venv/bin/python mcp_server/server.py     # transport stdio
```

### Configuration à coller dans Claude (`claude_desktop_config.json` ou `.mcp.json`)

```json
{
  "mcpServers": {
    "frameko": {
      "command": "/Users/mathieu/Operations/Kosmio/30-Axe3-Certifiko/Developpement/Frameko/proto/.venv/bin/python",
      "args": ["/Users/mathieu/Operations/Kosmio/30-Axe3-Certifiko/Developpement/Frameko/proto/mcp_server/server.py"]
    }
  }
}
```

Outils exposés : `list_frameworks`, `get_framework`, `search_requirements`, `nearest_requirements`,
`propose_mapping`, `compare_frameworks`, `start_assessment`, `answer_assessment`, `get_assessment_result`.

## Ingestion IA (rattachement d'un nouveau référentiel)

Étape « rattachement » du pipeline : pour chaque exigence d'un nouveau référentiel, proposer son
critère commun et son degré (`equivautA`, `plusStrictQue`, `plusLargeQue`, `rapprocheDe`).

**Approche recommandée — MCP-first (Claude pilote).** L'outil MCP `propose_mapping(criterion_text)`
renvoie les critères communs candidats (par similarité) **et des précédents** (exigences proches
déjà qualifiées, avec leur degré). Claude choisit le rattachement et le degré. Aucune clé externe.

**Voie optionnelle — stack OpenAI (batch autonome).** Quand aucun agent n'est dans la boucle :

```bash
# Mode MCP-first : produit les shortlists à valider (aucune clé requise)
.venv/bin/python scripts/ingest_framework.py --csv nouveau.csv --slug mon-label --title "Mon Label"

# Mode autonome : OpenAI choisit critère commun + degré + confiance + justification
.venv/bin/python scripts/ingest_framework.py --csv nouveau.csv --slug mon-label --title "Mon Label" --llm
```

Le script est **dry-run** : il écrit `proposals.json` (aucune écriture en base). La validation puis
l'insertion restent une étape humaine séparée. Variables `.env` : `OPENAI_API_KEY`, `OPENAI_MODEL`
(défaut `gpt-4o-mini`). Le CSV doit contenir au moins une colonne « Critère ».

## Lancer l'UI web

```bash
.venv/bin/python web/app.py               # http://127.0.0.1:8080
```

Trois onglets : **Recherche** (sémantique), **Comparaison** (couverture de deux référentiels),
**Auto-évaluation** (réponses par critère commun + taux de couverture).

## Trois exemples d'appels (MCP)

**1. Recherche d'une exigence sur le thème de l'eau**
```
search_requirements(query="gestion et économie de l'eau d'irrigation")
→ critère commun c-024 « Usage efficient et économie de l'eau » (sim ~0,81)
  + exigences voisines (planetproof 6.29, vivaifiori 3.02, plante-bleue 6, florverde 5.8…) avec degré
```

**2. Comparer Florverde et PlanetProof**
```
compare_frameworks(a="florverde", b="planetproof")
→ { communs_partages: 22, seulement_a: 29, seulement_b: 0 }
  + détail par critère commun (nombre d'exigences de chaque référentiel)
```

**3. Auto-évaluation courte**
```
start_assessment(framework="charte-qualite-fleurs")        → assessment_id
answer_assessment(assessment_id, common_criterion_label="…", status="conforme")
get_assessment_result(assessment_id)
→ { total_common: 13, conforme: 1, coverage_rate: 0.0769, gaps: [...] }
```

## Scénario de vérification de bout en bout

1. Démarrer le serveur MCP (ou l'UI web).
2. **Rechercher** une exigence sur l'eau → `search_requirements("…eau d'irrigation")` renvoie
   le critère commun `c-024` et les exigences proches de plusieurs référentiels avec leur degré.
3. **Comparer** Florverde et PlanetProof → `compare_frameworks("florverde","planetproof")`
   renvoie 22 critères communs partagés.
4. **Auto-évaluer** : `start_assessment("charte-qualite-fleurs")`, répondre à quelques critères
   communs, puis `get_assessment_result` → taux de couverture pondéré et liste des écarts.
   Le bénéfice du socle commun : une réponse vaut pour tous les référentiels rattachés au même
   critère commun.

## Hors périmètre du proto

SPARQL / miroir RDF, gestion des droits et licences ISO/AFNOR, multi-tenant, facturation.
La région du pooler Supabase (`DATABASE_POOLER_URL`) reste à confirmer ; le runtime utilise la
connexion directe `DATABASE_URL` par défaut (`USE_POOLER=0`).
