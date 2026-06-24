# Brief de développement pour Claude Code , proto Frameko

## Contexte

Frameko est une plateforme d'agrégation de référentiels et normes. Une ontologie a déjà été produite (extension de CCCEV, socle commun de 51 critères, 9 référentiels horticoles, 876 critères rapprochés et qualifiés). L'objectif de ce proto est de poser le squelette technique de la V1 : charger l'ontologie dans Supabase, calculer des embeddings, et exposer trois services via un serveur MCP.

La spécification fonctionnelle complète est dans `../ONTOLOGIE/application/Specification_plateforme_referentiels.md`. La note d'architecture du socle générique est dans `../ONTOLOGIE/socle-generique/Architecture_cible_socle_generique.md`. Lis ces deux documents avant de commencer.

## Objectif du proto

Un proto fondation, qui devient le socle de la V1 (pas une démo jetable). Il doit permettre, depuis Claude via MCP, de rechercher des exigences, d'analyser la proximité entre référentiels, et de faire une auto-évaluation de conformité.

## Décisions déjà arbitrées (ne pas rediscuter)

- Base de données : Supabase (Postgres managé) avec l'extension pgvector. Pas de triple store ni de SPARQL dans le proto.
- Langage : Python.
- Embeddings : modèle local `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions), pour éviter toute clé API externe. Prévoir une variable pour basculer vers un fournisseur hébergé plus tard.
- Serveur MCP : `fastmcp` (Python).
- Pas de gestion de droits, de licences, de multi-tenant ni de facturation dans le proto. Uniquement les référentiels publics déjà alignés.

## Sources de données (déjà présentes dans le dépôt)

Dans `../ONTOLOGIE/` :
- `socle-generique/socle-commun-generique.ttl` : la taxonomie du socle (7 catégories, 13 thèmes, 51 critères communs, 7 domaines). Source canonique pour les catégories, thèmes et critères communs. À lire avec `rdflib`.
- `export_tous_criteres.csv` : les 876 critères de référentiel. Colonnes : `Référentiel, Référence, Critère, Thème, Niveau, Critère commun, Degré`.
- `export_referentiels.csv` : métadonnées des 9 référentiels. Colonnes : `Référentiel, Éditeur, Version, Couverture, Statut`.
- `socle-generique/profil-shacl.ttl` : les contraintes du modèle (pour information).

Règle de jointure importante : dans `export_tous_criteres.csv`, la colonne `Critère commun` contient le libellé français exact du critère commun (`skos:prefLabel` du socle). Rattache chaque critère de référentiel à son critère commun par correspondance exacte sur ce libellé. Déduis le thème depuis le critère commun (via le socle TTL), pas depuis la colonne `Thème` du CSV qui utilise des libellés d'affichage différents.

## Configuration

Les identifiants Supabase sont dans `.env` (déjà présent, non versionné). Variables disponibles : `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `DATABASE_URL`, `DATABASE_POOLER_URL`, et les variables `SUPABASE_DB_*`.

Contraintes de sécurité : ne jamais coder en dur un secret, toujours lire depuis `.env`. La clé secrète et le mot de passe restent côté serveur. Ne jamais commiter `.env` (déjà dans `.gitignore`). À confirmer dans le tableau de bord Supabase : la région exacte du pooler dans `DATABASE_POOLER_URL`. Pour les migrations, utilise la connexion directe `DATABASE_URL`.

## Structure de dépôt cible

```
proto/
  .env                      (existe, ne pas commiter)
  .env.example              (existe)
  .gitignore                (existe)
  requirements.txt
  README.md                 (à écrire : comment lancer)
  db/
    schema.sql              (tables + extension pgvector)
    functions.sql           (fonctions RPC)
  scripts/
    load_data.py            (charge le socle et les référentiels)
    build_embeddings.py     (calcule et stocke les embeddings)
  mcp_server/
    server.py               (serveur MCP fastmcp)
    db.py                   (accès Supabase / Postgres)
```

## Modèle de données (db/schema.sql)

Active l'extension : `create extension if not exists vector;`

Tables minimales :
- `domain(id, slug, label_fr, label_en)`
- `category(id, slug, label_fr, label_en, domain_slug)`
- `theme(id, slug, label_fr, label_en, category_slug)`
- `common_criterion(id, code, label_fr, theme_slug, embedding vector(384))`
- `framework(id, slug, title, publisher, version, coverage, status)`
- `framework_criterion(id, framework_slug, reference, label, theme_slug, level, degree, common_criterion_id, embedding vector(384))`
- `assessment(id, framework_slug, status, created_at)`
- `assessment_answer(id, assessment_id, common_criterion_id, status, note)`

Index : index `ivfflat` ou `hnsw` sur les colonnes `embedding`. Clés étrangères cohérentes. `degree` contraint aux valeurs `equivautA, plusStrictQue, plusLargeQue, rapprocheDe`.

## Tâches séquencées

### Tâche 1 , Initialisation
Créer `requirements.txt` (`supabase`, `psycopg2-binary` ou `psycopg`, `python-dotenv`, `rdflib`, `sentence-transformers`, `fastmcp`, `pandas`). Vérifier la connexion à Postgres via `DATABASE_URL`.
Acceptation : un script de test affiche la version de Postgres et confirme que l'extension `vector` peut être créée.

### Tâche 2 , Schéma
Écrire `db/schema.sql` et l'appliquer sur la base via `DATABASE_URL`.
Acceptation : toutes les tables existent, l'extension vector est active.

### Tâche 3 , Chargement des données
Écrire `scripts/load_data.py` qui :
1. lit `socle-commun-generique.ttl` avec rdflib et insère domaines, catégories, thèmes, critères communs (avec leur thème et catégorie via `skos:broader`),
2. lit `export_referentiels.csv` et insère les 9 référentiels,
3. lit `export_tous_criteres.csv` et insère les 876 critères de référentiel, en rattachant chacun à son critère commun par le libellé français, et en reprenant `Niveau` et `Degré`.
Acceptation : la base contient 7 domaines, 7 catégories, 13 thèmes, 51 critères communs, 9 référentiels, 876 critères, et aucun critère sans critère commun rattaché. Fournir une requête de contrôle qui affiche ces comptes.

### Tâche 4 , Embeddings
Écrire `scripts/build_embeddings.py` qui calcule l'embedding du libellé de chaque critère commun et de chaque critère de référentiel avec le modèle local, et le stocke dans la colonne `embedding`.
Acceptation : aucune ligne avec embedding nul dans `common_criterion` et `framework_criterion`.

### Tâche 5 , Fonctions RPC (db/functions.sql)
1. `match_criteria(query_embedding vector, k int)` : retourne les `k` critères communs les plus proches (distance cosinus pgvector `<=>`), avec leur thème.
2. `nearest_framework_criteria(query_embedding vector, k int)` : retourne les critères de référentiel les plus proches, avec leur référentiel et leur degré.
3. `framework_coverage(framework_a text, framework_b text)` : pour deux référentiels, retourne par critère commun le nombre de critères de chaque référentiel rattachés, afin de mesurer le recouvrement.
4. `assessment_result(assessment_id uuid)` : retourne le taux de couverture (réponses conformes sur total des critères communs couverts par le référentiel cible) et la liste des écarts.
Acceptation : chaque fonction renvoie un résultat cohérent sur des cas de test fournis.

### Tâche 6 , Serveur MCP (mcp_server/server.py)
Avec fastmcp, exposer les outils :
- `list_frameworks()` et `get_framework(slug)`
- `search_requirements(query, framework?, theme?)` : recherche sémantique (embed de la requête côté serveur puis `match_criteria` et `nearest_framework_criteria`)
- `nearest_requirements(text)` : pour un texte d'exigence, le critère commun de rattachement et les exigences proches des autres référentiels avec leur degré
- `compare_frameworks(a, b)` : appelle `framework_coverage`
- `start_assessment(framework)`, `answer_assessment(assessment_id, common_criterion_label, status, note?)`, `get_assessment_result(assessment_id)`
L'embedding de requête est calculé côté serveur avec le même modèle local.
Acceptation : le serveur démarre, et chaque outil renvoie un résultat sur un appel manuel. Fournir dans le README la configuration MCP à coller (commande de lancement) pour brancher le serveur dans Claude.

### Tâche 7 , README
Documenter l'installation, l'ordre d'exécution des scripts, le lancement du serveur MCP, et trois exemples d'appels (recherche, comparaison, auto-évaluation).

## Vérification finale

Un scénario de bout en bout : démarrer le serveur MCP, rechercher une exigence sur le thème de l'eau, comparer Florverde et PlanetProof, lancer une auto-évaluation courte sur un référentiel et obtenir un taux de couverture. Documenter ce scénario dans le README.

## Hors périmètre du proto

SPARQL et miroir RDF, gestion des droits et licences ISO et AFNOR, multi-tenant, facturation, frontend web. Ces éléments viendront après et ne doivent pas ralentir le proto.
