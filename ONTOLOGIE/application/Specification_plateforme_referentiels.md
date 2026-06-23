# Spécification : plateforme d'agrégation et d'exploitation de référentiels

**Projet** : Floriscore / Kosmio
**Nom de travail** : Socle Référentiels (Standards Commons Platform)
**Version** : 0.1.0 (23 juin 2026)
**Objet** : spécifier une application générique qui héberge l'ontologie créée, l'alimente progressivement avec de nouveaux référentiels analysés par un LLM, et expose des services via une API et un serveur MCP.

## 1. Vision

Construire un socle de connaissance des référentiels et normes, vivant et extensible, qui sait deux choses : ingérer un référentiel quelconque pour le rattacher au socle commun d'exigences, et exposer cette connaissance à des humains et à des applications tierces. La première version intègre l'ontologie existante (9 référentiels horticoles, 51 critères communs, profil SHACL) et pose l'infrastructure d'agrégation. Les versions suivantes ajoutent des référentiels, des domaines et des normes sous licence.

## 2. Acteurs

**Curateur ontologie** : valide les rattachements proposés par le LLM, gère le socle commun, publie les versions.
**Contributeur** : dépose un nouveau référentiel à ingérer.
**Éditeur de norme** (ISO, AFNOR) : fournit le contenu sous contrat de distribution ; la plateforme gère ses droits.
**Solution tierce** : consomme l'API pour enrichir son produit (proximité, équivalences).
**Organisation auto-évaluée** : utilise le service de conformité pour se situer face à une norme.
**Administrateur** : gère les comptes, les droits, la facturation, l'observabilité.

## 3. Services exposés

Trois services structurants en première intention, plus des services d'administration.

**S1. Récupérer les exigences d'un référentiel ou d'une norme.** Retourne les critères d'un référentiel donné, filtrables par thème, niveau, domaine. Le contenu public est rendu intégralement ; le contenu sous licence (ISO, AFNOR) est servi selon les droits du demandeur, sous forme de résumé reformulé tant que le contrat ne couvre pas le verbatim.

**S2. Proximité et analyse croisée.** À partir d'une exigence ou d'un référentiel entier, retourne les critères communs les plus proches, les exigences équivalentes ou proches dans les autres référentiels, et une analyse de couverture (ce que tel label couvre par rapport à tel autre, avec les degrés de rapprochement).

**S3. Auto-évaluation de conformité.** L'utilisateur choisit un référentiel cible et répond aux exigences. Comme les réponses se rattachent aux critères communs, elles se réutilisent d'un référentiel à l'autre : répondre une fois sur un thème renseigne plusieurs labels. Le système calcule un taux de couverture pondéré, la liste des écarts, et les équivalences déjà acquises ailleurs.

Services complémentaires : recherche plein texte et sémantique, export (Turtle, CSV, JSON-LD), abonnement aux mises à jour de normes, tableaux de bord de couverture.

## 4. Architecture cible

Quatre plans logiques.

**Plan d'ingestion** : dépôt de la source, extraction, normalisation et traduction, calcul d'embeddings, proposition de rattachement par le LLM, validation humaine, contrôle SHACL, versionnement.

**Socle de connaissance** : la base de données qui stocke le modèle (catégories, thèmes, domaines, critères communs), les référentiels et leurs critères, les rapprochements qualifiés avec provenance, les embeddings, les versions, et les droits.

**Plan d'exposition** : une API REST (et GraphQL en option) et un serveur MCP, adossés au même socle, avec authentification, quotas et gestion des droits.

**Plan de consommation** : interface de curation, interface d'auto-évaluation, et intégrations tierces.

Le schéma `architecture_plateforme.svg` accompagne ce document.

## 5. Choix de la base de données

Le besoin combine trois natures de données : sémantique et graphe (RDF, taxonomie SKOS, rapprochements, conformité CCCEV, requêtes de proximité par chemins), vectorielle (similarité pour l'ingestion et la proximité), et applicative et relationnelle (comptes, droits, licences, facturation, journaux). Aucun moteur unique n'excelle sur les trois.

### Comparatif

| Option | Forces | Limites |
|---|---|---|
| Triple store (GraphDB, Fuseki, Oxigraph, Stardog) | SPARQL natif, raisonnement, fidélité au standard, interopérabilité maximale | Pas d'auth ni de droits applicatifs, exploitation plus lourde, vecteurs souvent externes |
| Neo4j + n10s + index vectoriel | Graphe de propriétés performant pour la proximité, import RDF, vecteurs intégrés, un seul moteur | SPARQL non natif, modèle propriétaire, coût à l'échelle |
| Postgres / Supabase + pgvector | Relationnel mûr, auth et droits au niveau ligne, vecteurs intégrés, API et fonctions natives, rapide à livrer | Le graphe et le SPARQL doivent être ajoutés en couche |

### Recommandation

Pour la V1, **Postgres via Supabase, avec pgvector**, comme système de référence. Raison : la gestion des comptes, des droits, des licences ISO et AFNOR et des quotas est relationnelle et critique, Supabase la fournit nativement (authentification, sécurité au niveau ligne, API, fonctions). Les embeddings vivent dans la même base avec pgvector, ce qui simplifie l'ingestion et la proximité.

En parallèle, **un miroir RDF en lecture** (Oxigraph ou GraphDB) reconstruit depuis Postgres et expose un point SPARQL pour l'interopérabilité et la conformité au standard. Le fichier Turtle déjà produit reste l'export canonique. Le graphe relationnel de rapprochements suffit pour S2 en V1 ; le SPARQL sert l'interopérabilité externe et les requêtes sémantiques avancées.

Bascule possible vers un triple store de premier plan, ou vers Neo4j si les traversées de graphe deviennent le goulot, sans changer le modèle conceptuel puisque tout dérive de l'ontologie. Neo4j reste le meilleur candidat mono-moteur si l'on veut éviter le double stockage à terme.

## 6. Modèle de données

Tables principales (Postgres), reflet direct de l'ontologie.

```
domain(id, slug, label_fr, label_en)
category(id, slug, label_fr, label_en, domain_id)          -- 7 catégories transverses
theme(id, slug, label_fr, label_en, category_id)            -- 13 thèmes
common_criterion(id, code, label_fr, label_en, theme_id,    -- socle commun
                 definition, embedding vector, iri)
framework(id, slug, title, publisher, version, domain_id,
          type, jurisdiction, language, license_id, status, iri)
framework_criterion(id, framework_id, reference, label,     -- critères de référentiel
                    theme_id, level, embedding vector, iri,
                    source_excerpt, is_verbatim_allowed)
mapping(id, framework_criterion_id, common_criterion_id,    -- rapprochement
        degree, confidence, method, validated_by, validated_at)
framework_version(id, framework_id, version, valid_from, supersedes_id)
license(id, holder, scope, allows_verbatim, terms_url)
entitlement(id, consumer_id, framework_id, scope, expires_at)
evidence_type(id, label, description)
criterion_evidence(framework_criterion_id, evidence_type_id)
assessment(id, org_id, framework_id, status, score, created_at)
assessment_answer(id, assessment_id, common_criterion_id,   -- réponse par critère commun
                  status, note, evidence_url)
org(id, name), app_user(id, org_id, role), api_key(...)
ingestion_job(id, source_ref, type, status, log)
provenance(id, subject_iri, actor, method, confidence, ts)
```

Le degré de rapprochement (`degree`) prend les valeurs `equivautA`, `plusStrictQue`, `plusLargeQue`, `rapprocheDe`, exactement comme dans l'ontologie. La réponse d'auto-évaluation se fait au niveau du critère commun, ce qui rend la réutilisation entre référentiels native.

## 7. Pipeline d'ingestion assisté par LLM

Cinq étapes, déclenchées par un dépôt de source (PDF, tableur, page web).

1. **Extraction** : un parseur par type de source (checklist numérotée, clauses normatives, système à points, références réglementaires) produit une liste de couples code et intitulé.
2. **Normalisation** : nettoyage, traduction en français, détection du niveau d'exigence.
3. **Vectorisation** : calcul d'un embedding par critère.
4. **Rattachement proposé** : recherche des critères communs les plus proches par similarité vectorielle, puis un LLM choisit le critère commun et propose le degré de rapprochement, avec un score de confiance et une justification courte. S'il n'existe pas de critère commun adéquat, le LLM propose d'en créer un.
5. **Validation et publication** : le curateur valide ou corrige dans une interface dédiée, le contrôle SHACL s'exécute, puis les critères sont publiés et versionnés. Toute décision est tracée (acteur, méthode, confiance).

Ce pipeline transforme le mapping manuel actuel en revue assistée, ce qui permet d'absorber un volume croissant de référentiels.

## 8. API

API REST versionnée (`/v1`), authentifiée par clé pour les tiers et par jeton pour l'interface. Points principaux.

**Référentiels et exigences (S1)**
- `GET /v1/frameworks` liste et filtres (domaine, type, éditeur, statut)
- `GET /v1/frameworks/{id}` métadonnées et version
- `GET /v1/frameworks/{id}/criteria` exigences, filtrables par thème, niveau ; rendu selon les droits
- `GET /v1/criteria/{id}` détail d'une exigence

**Proximité et analyse croisée (S2)**
- `POST /v1/match` en entrée un texte d'exigence libre, en sortie les critères communs proches et les exigences équivalentes par référentiel, avec degrés
- `GET /v1/frameworks/{a}/compare/{b}` matrice de couverture entre deux référentiels
- `GET /v1/common-criteria/{id}/frameworks` tous les critères rattachés à un critère commun

**Auto-évaluation (S3)**
- `POST /v1/assessments` crée une auto-évaluation pour un référentiel cible
- `PUT /v1/assessments/{id}/answers` enregistre les réponses au niveau des critères communs
- `GET /v1/assessments/{id}/result` score pondéré, écarts, équivalences acquises sur d'autres référentiels

**Ingestion et curation**
- `POST /v1/ingestion-jobs` dépose une source à analyser
- `GET /v1/ingestion-jobs/{id}` état et propositions de rattachement
- `POST /v1/mappings/{id}/validate` valide ou corrige un rattachement

**Export et interopérabilité**
- `GET /v1/export?format=turtle|jsonld|csv`
- point SPARQL en lecture sur le miroir RDF

Webhooks pour notifier les abonnés d'une nouvelle version de norme.

## 9. Serveur MCP

Le serveur MCP expose la même connaissance à des agents et assistants (dont Claude), en miroir de l'API. Outils proposés.

- `search_requirements(query, filters)` recherche sémantique et plein texte
- `get_framework(id)` et `list_frameworks(filters)`
- `nearest_requirements(text|criterion_id)` proximité, retourne critères communs et voisins inter-référentiels avec degré
- `compare_frameworks(a, b)` analyse de couverture
- `assess_conformity(framework_id, answers)` calcule couverture, écarts, équivalences
- `ingest_framework(source)` lance une ingestion (réservé aux rôles autorisés)
- `propose_mapping(criterion_text)` propose un rattachement à valider

Les outils respectent les droits : un agent sans entitlement sur une norme sous licence reçoit les résumés, pas le verbatim.

## 10. Détail des services

### S1, exigences et gestion des droits

Le contenu public (Florverde, FlorEcuador, PlanetProof, etc.) est servi intégralement. Pour ISO et AFNOR, tant que le contrat de distribution ne couvre pas le verbatim, l'API renvoie un résumé reformulé de l'exigence plus la référence de clause, et signale le statut sous licence. Le modèle `license` et `entitlement` arbitre ce que chaque consommateur peut récupérer. Cette séparation est prévue dès la V1 pour que l'ouverture aux normes payantes ne demande aucune refonte.

### S2, proximité

Combinaison de deux signaux : la similarité vectorielle entre embeddings, et le chemin de graphe via les critères communs (deux exigences rattachées au même critère commun sont voisines, pondérées par leur degré). En sortie : pour une exigence donnée, le critère commun de rattachement, les exigences équivalentes ou proches des autres référentiels, et un indice de proximité. Pour un référentiel entier face à un autre : un taux de recouvrement et la liste des exigences sans correspondance.

### S3, auto-évaluation

L'utilisateur répond au niveau des critères communs (conforme, partiel, non conforme, sans objet), avec preuve éventuelle. Le score est une couverture pondérée par `weight`. Le résultat indique le taux de conformité au référentiel cible, les écarts priorisés par niveau d'exigence, et surtout les équivalences : les réponses déjà fournies qui satisfont d'autres référentiels rattachés aux mêmes critères communs. C'est le bénéfice direct du socle commun pour une entreprise multi-certifiée.

## 11. Sécurité, droits et conformité

Authentification et autorisation par Supabase (jetons pour l'interface, clés pour les tiers), sécurité au niveau ligne pour isoler les données par organisation. Modèle d'entitlements pour le contenu sous licence, avec distinction stricte entre résumé et verbatim. Journal d'audit complet des accès au contenu sous licence, exigé par les contrats ISO et AFNOR. Données d'auto-évaluation considérées comme sensibles et cloisonnées par organisation, conformément au RGPD. Provenance et confiance attachées à chaque rapprochement pour la traçabilité.

## 12. Exigences non fonctionnelles

Multilingue dès le modèle (libellés fr et en, extensible). Versionnement de tout référentiel et du socle commun. Observabilité (journaux, métriques, traçabilité des ingestions). Performance de la recherche vectorielle via index pgvector. Reproductibilité du miroir RDF depuis la base. Maîtrise des coûts LLM en réservant l'appel au modèle à l'étape de rattachement et de résumé.

## 13. Découpage en versions

**V1, socle exploitable.** Intégrer l'ontologie existante (9 référentiels, socle commun, profil SHACL) dans Postgres et pgvector. API en lecture pour S1, S2 et une première version de S3. Serveur MCP en lecture. Interface de curation et interface d'auto-évaluation simples. Ingestion semi-manuelle (extraction outillée, rattachement assisté, validation humaine). Miroir RDF et export.

**V2, agrégation à l'échelle.** Pipeline d'ingestion LLM complet et versionné. Intégration des premières normes ISO sous licence avec gestion des droits. Clés API, quotas et facturation pour les tiers. Point SPARQL public.

**V3, commun numérique et fédération.** Contributions externes encadrées, alignements ESRS, GRI et ODD, IRIs déréférençables, gouvernance ouverte du socle.

## 14. Stack technique proposée

Base et back-office : Supabase (Postgres, Auth, Storage, Edge Functions) avec pgvector. Service applicatif et MCP : Node TypeScript ou Python, exposant l'API REST et le serveur MCP. Embeddings et rattachement : un modèle d'embeddings multilingue plus un LLM pour le choix du critère commun et les résumés. Miroir sémantique : Oxigraph ou GraphDB pour le point SPARQL, reconstruit depuis Postgres. Frontend : Next.js pour la curation et l'auto-évaluation. Validation : pyshacl dans le pipeline d'ingestion.

## 15. Risques et dépendances

La négociation des contrats de distribution avec ISO et AFNOR conditionne l'accès au contenu normatif ; la plateforme est conçue pour fonctionner d'abord sur le contenu public et activer le contenu sous licence sans refonte. La qualité des rattachements dépend de la revue humaine ; le score de confiance et la traçabilité encadrent ce risque. Le double stockage Postgres et miroir RDF ajoute une synchronisation à maintenir ; il reste optionnel en V1 si le SPARQL externe n'est pas requis immédiatement.

## 16. Décisions à confirmer

Trois arbitrages restent ouverts : confirmer Postgres et pgvector pour la V1 plutôt qu'un triple store ou Neo4j en moteur unique ; décider si le point SPARQL est requis dès la V1 ou différé ; fixer le périmètre exact de la V1 sur S3 (auto-évaluation complète ou réduite à la couverture). Ces choix orientent l'effort de la première itération.
