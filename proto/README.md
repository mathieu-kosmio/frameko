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
    03_auth_rls.sql     table org + RLS + rôle applicatif frameko_app
  scripts/
    test_connection.py  vérifie la connexion + l'extension vector
    apply_sql.py        applique un fichier .sql via DATABASE_URL
    load_data.py        charge le socle TTL + les 2 CSV
    build_embeddings.py calcule et stocke les embeddings
    setup_app_role.py   provisionne frameko_app (LOGIN) + APP_DATABASE_URL
    create_org.py       crée une organisation et émet son jeton
    extract_source.py   ingestion étape 1 : source (tableur/PDF) → criteria.csv
    ingest_framework.py ingestion étape 2 : rattachement → proposals.json
    apply_ingestion.py  ingestion étape 3 : insertion du référentiel validé
  mcp_server/
    db.py               accès Postgres (+ org_scope RLS)
    auth.py             résolution d'organisation par jeton
    embeddings.py       service d'embedding (partagé)
    server.py           serveur MCP fastmcp (9 outils)
  web/
    app.py              UI web Starlette (+ route /docs)
    index.html          interface (recherche, comparaison, auto-évaluation)
    docs.html           documentation utilisateur (lien discret dans la console)
  tests/                suite pytest (RPC, MCP, ingestion, extraction)
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

## Serveur MCP — deux modes

### A. Local (stdio, mono-organisation)

```bash
.venv/bin/python mcp_server/server.py     # transport stdio
```

Configuration à coller dans Claude (`claude_desktop_config.json` ou `.mcp.json`).
L'organisation (pour l'auto-évaluation) vient de `FRAMEKO_ORG_TOKEN` :

```json
{
  "mcpServers": {
    "frameko": {
      "command": "/…/proto/.venv/bin/python",
      "args": ["/…/proto/mcp_server/server.py"],
      "env": { "FRAMEKO_ORG_TOKEN": "<jeton émis par create_org.py>" }
    }
  }
}
```

### B. SaaS (HTTP, hébergé, multi-organisation)

Un seul serveur sert toutes les organisations ; chacune s'authentifie **par requête**
via le header `Authorization: Bearer <jeton>`. L'isolation des données est garantie par RLS.

```bash
FRAMEKO_MCP_TRANSPORT=http FRAMEKO_MCP_HOST=0.0.0.0 FRAMEKO_MCP_PORT=8765 \
  .venv/bin/python mcp_server/server.py     # http://<host>:8765/mcp/
```

Côté client (serveur MCP distant, un jeton par organisation) :

```json
{
  "mcpServers": {
    "frameko": {
      "url": "https://<votre-hôte>/mcp/",
      "headers": { "Authorization": "Bearer <jeton de l'organisation>" }
    }
  }
}
```

Recherche et comparaison fonctionnent sans jeton (données publiques) ; l'auto-évaluation
exige un jeton valide. Le service utilise des **pools de connexions** (concurrence
multi-utilisateurs) ; déployer derrière HTTPS et provisionner les organisations avec
`scripts/create_org.py`.

### Déploiement (Docker)

```bash
# Image du serveur MCP (contexte = proto/)
docker compose up -d                # MCP HTTP en interne, modèle en volume

# Avec HTTPS automatique (Let's Encrypt via Caddy)
DOMAIN=frameko.example.org docker compose --profile https up -d
```

- `Dockerfile` : image Python 3.13 (~540 Mo, sans torch), le modèle d'embedding est mis en cache
  dans un volume (`FRAMEKO_MODEL_CACHE=/data/models`) → pas de re-téléchargement au redémarrage.
- Secrets via `.env` (`env_file`), **jamais** copiés dans l'image (`.dockerignore`).
- Sonde `GET /health` (vérifie l'accès base) utilisée par le `HEALTHCHECK` du conteneur.
- `deploy/Caddyfile` termine le TLS et transmet le header `Authorization` au backend.

> **Prérequis réseau — connexion base depuis un conteneur.** Le endpoint *direct* Supabase
> (`db.<ref>.supabase.co:5432`) est **IPv6-only** : il est injoignable depuis le réseau Docker
> IPv4 par défaut (`Network is unreachable`). En conteneur, utiliser le **pooler Supavisor (IPv4)** :
> renseigner `DATABASE_POOLER_URL` (Dashboard → Database → Connection pooling, **transaction**,
> region exacte) et `USE_POOLER=1`. Prévoir aussi un `APP_DATABASE_URL` via le pooler pour le
> rôle `frameko_app`. L'image a été construite et le serveur démarre (`/mcp/` + `/health`
> répondent) ; le test base en conteneur reste à finaliser une fois le pooler confirmé.

Outils exposés : `list_frameworks`, `get_framework`, `search_requirements`, `nearest_requirements`,
`propose_mapping`, `compare_frameworks`, `start_assessment`, `answer_assessment`, `get_assessment_result`.

## Ingestion d'un nouveau référentiel (pipeline en 3 étapes)

Aucune écriture en base avant **validation** : les étapes 1-2 produisent des fichiers, l'étape 3
insère seulement après contrôle des degrés.

```bash
# 1. EXTRACTION — source (tableur .xlsx/.csv ou PDF) → criteria.csv (Référence, Critère)
.venv/bin/python scripts/extract_source.py --source source.xlsx --out criteria.csv
#    PDF : heuristique de numérotation, ou --llm pour une extraction assistée OpenAI

# 2. RATTACHEMENT — criteria.csv → proposals.json (critère commun + degré proposés)
.venv/bin/python scripts/ingest_framework.py --csv criteria.csv --slug mon-label --title "Mon Label"
#    --llm : OpenAI choisit critère commun + degré + confiance + justification

# 3. APPLY — insère le référentiel validé (framework + critères + mappings + embeddings)
.venv/bin/python scripts/apply_ingestion.py --proposals proposals.json [--replace]
```

**Rattachement — deux voies :**
- **MCP-first (recommandé).** L'outil MCP `propose_mapping(criterion_text)` renvoie les critères
  communs candidats **et des précédents** (exigences proches déjà qualifiées, avec leur degré) ;
  Claude choisit le rattachement et le degré. Aucune clé externe.
- **OpenAI (batch autonome).** `ingest_framework.py --llm` quand aucun agent n'est dans la boucle.
  Variables `.env` : `OPENAI_API_KEY`, `OPENAI_MODEL` (défaut `gpt-4o-mini`).

**Garde-fous de `apply` :** refuse toute proposition sans degré (validation requise) ou avec un
critère commun inconnu ; `--replace` est requis pour réinsérer un slug existant. Les degrés des
propositions MCP-first (laissés à `null`) doivent être complétés dans `proposals.json` avant `apply`.

## Auth & isolation des auto-évaluations (RLS multi-organisation)

Les auto-évaluations sont des **données sensibles** : chaque organisation ne voit que les siennes.
L'isolation est garantie **au niveau de la base** par Row-Level Security, pas seulement par l'app.

Mise en place (après le schéma) :

```bash
.venv/bin/python scripts/apply_sql.py db/03_auth_rls.sql   # table org + RLS + rôle frameko_app
.venv/bin/python scripts/setup_app_role.py                 # mot de passe LOGIN + APP_DATABASE_URL
.venv/bin/python scripts/create_org.py --slug acme --name "ACME Fleurs"   # → émet un jeton (1 fois)
```

**Comment ça marche.** Le rôle Supabase `postgres` possède `BYPASSRLS` (il ignore toute policy).
Les opérations d'évaluation passent donc par un rôle dédié **`frameko_app`** (sans ce privilège,
`APP_DATABASE_URL`), dans une transaction où l'organisation courante est fixée par
`SET LOCAL app.current_org_id`. La policy RLS `org_id = current_setting('app.current_org_id')`
cloisonne lecture **et** écriture.

- **Web** : onglet Auto-évaluation → se connecter avec le jeton (session signée par cookie).
- **MCP** : exporter `FRAMEKO_ORG_TOKEN=<jeton>` avant de lancer le serveur ; les outils
  `start_assessment` / `answer_assessment` / `get_assessment_result` refusent sans jeton valide.

Recherche et comparaison restent publiques (données de référentiels, non sensibles).

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Suite d'intégration (18 tests) : fonctions RPC, 9 outils MCP, boucle d'ingestion (apply + garde-fous),
extraction tableur, et **isolation RLS** (une organisation ne lit/écrit pas les évaluations d'une
autre). Les tests se sautent proprement si `DATABASE_URL`/`APP_DATABASE_URL` sont absents ou la base vide.

## Lancer l'UI web

```bash
.venv/bin/python web/app.py               # http://127.0.0.1:8080
```

Trois onglets : **Recherche** (sémantique), **Comparaison** (couverture de deux référentiels),
**Auto-évaluation** (réponses par critère commun + taux de couverture). Un lien discret
**Documentation ↗** (en-tête) ouvre la doc utilisateur servie sur `/docs`.

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
