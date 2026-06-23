# Architecture cible : un socle générique multi-domaine pour les référentiels

**Projet** : Floriscore / Kosmio
**Version** : 0.1.0 (23 juin 2026)
**Objet** : rendre l'ontologie des référentiels générique, pour intégrer un grand nombre de référentiels dans plusieurs domaines, y compris les normes ISO.

## 1. D'où l'on part

L'ontologie actuelle couvre neuf référentiels horticoles, rapprochés sur 51 critères communs. Elle fonctionne, mais son socle commun est dérivé d'un seul label (Florverde) et porte cette empreinte : libellés et identifiants marqués horticulture, grille plate de 51 entrées, thèmes orientés filière florale. Pour passer à l'échelle multi-domaine, le socle commun doit devenir un vocabulaire neutre, hiérarchique et gouverné, indépendant du domaine d'origine.

## 2. Principes de conception

Cinq principes guident la cible.

Séparer le modèle des instances. Le modèle (classes, propriétés, profil) est stable et générique. Les référentiels et leurs critères sont des données qui s'ajoutent sans toucher au modèle.

Garder CCCEV comme socle normatif. Le vocabulaire européen reste la fondation. L'extension générique `std:` se contente de spécialiser ses classes et d'ajouter les dimensions de classement et de rapprochement.

Neutraliser le socle commun. Identifiants opaques et stables, libellés multilingues, taxonomie hiérarchique plutôt que liste plate, dimension de domaine explicite.

Rendre l'ingestion contractuelle. Un profil applicatif et des contraintes SHACL valident automatiquement toute contribution, ce qui autorise l'ouverture à de nombreuses sources sans perte de cohérence.

Publier comme commun numérique. IRIs déréférençables, versions, traçabilité des rapprochements, alignements sur les référentiels mondiaux.

## 3. Le modèle générique

### 3.1 Cœur de modèle (`std:`)

Une fine extension de CCCEV, indépendante du domaine, définie dans `socle-commun-generique.ttl` :

- `std:Framework` (sous-classe de `cccev:ReferenceFramework`) : tout cadre d'exigences, label, norme ISO, réglementation ou charte.
- `std:FrameworkCriterion` et `std:CommonCriterion` (sous-classes de `cccev:Criterion`) : le critère tel que formulé par un référentiel, et le critère canonique du socle.
- `std:Domain`, `std:Category`, `std:Theme`, `std:RequirementLevel` : les axes de classement (concepts SKOS).
- `std:alignsWith` et ses sous-propriétés `std:equivalentTo`, `std:closeTo`, `std:broaderThan`, `std:narrowerThan` : le rapprochement qualifié, aligné sur les relations de correspondance SKOS.
- `std:weight` (sous-propriété de `cccev:weight`) : la pondération de scoring.

### 3.2 Socle commun en taxonomie à trois niveaux

Le socle est désormais un `skos:ConceptScheme` hiérarchique : Catégorie transverse, puis Thème, puis Critère commun.

Sept catégories transverses structurent le sommet, choisies pour traverser les domaines et recouvrir la structure haut niveau des normes de management : gouvernance management et conformité ; travail droits humains et conditions sociales ; santé et sécurité au travail ; environnement et ressources naturelles ; intrants matières et chaîne d'approvisionnement ; produit qualité et sécurité ; données traçabilité et transparence.

Sous ces catégories, treize thèmes, puis les critères communs. Les 51 critères communs horticoles existants sont migrés dans cette taxonomie, marqués du domaine horticulture, et reliés à leurs anciens identifiants par `skos:exactMatch`. L'ontologie horticole actuelle continue donc de fonctionner, tout en se branchant sur le socle générique.

### 3.3 La dimension Domaine

Un axe `std:Domain` orthogonal aux catégories : transverse, horticulture, forêt-bois, agroalimentaire, industrie, numérique, services. Les catégories et thèmes sont transverses. Un critère commun peut appartenir à un ou plusieurs domaines. Ajouter un domaine ne demande aucune modification du modèle.

## 4. Intégrer un nouveau référentiel

La procédure est identique pour tout référentiel, quel que soit le domaine :

1. Déclarer le `std:Framework` avec ses métadonnées (titre, éditeur, version, domaine, type, juridiction, langue).
2. Créer ses `std:FrameworkCriterion` (un par exigence), avec libellé, thème, niveau et référence d'origine.
3. Rapprocher chaque critère du critère commun le plus proche, avec le degré qualifié. Enrichir le socle si une exigence nouvelle n'a pas de critère commun correspondant.
4. Valider contre le profil SHACL.
5. Charger dans le triple store, l'export tabulaire et la base de travail.

## 5. Le patron d'intégration des normes ISO

Les normes ISO entrent dans le même modèle, avec trois particularités.

Structure par clauses. Chaque norme est un `std:Framework` de type norme de système de management. Chaque exigence (« shall ») d'une clause devient un `std:FrameworkCriterion`, rattaché à la clause comme regroupement. La référence d'origine est le numéro de clause.

Tronc commun Annexe SL. Les normes de management ISO partagent une structure haut niveau (contexte, leadership, planification, support, opérations, évaluation des performances, amélioration). Cette structure se rattache directement à la catégorie gouvernance du socle, ce qui donne une ossature commune à ISO 9001, 14001, 45001, 50001 et aux suivantes. Les exigences spécifiques se rattachent ensuite aux catégories de domaine (environnement, santé-sécurité, énergie).

Droits d'auteur. Le texte ISO est protégé. On stocke la référence de clause et un résumé reformulé de l'exigence, jamais le verbatim.

Normes pertinentes pour démarrer : ISO 14001 (environnement), ISO 14064 et 14067 (gaz à effet de serre et empreinte produit), ISO 14040 et 14044 (analyse de cycle de vie), ISO 50001 (énergie), ISO 45001 (santé-sécurité), ISO 26000 (responsabilité sociétale), ISO 9001 (qualité).

## 6. Le pipeline d'ingestion industrialisé

Pour passer de l'artisanat à l'échelle, quatre étapes standardisées, avec un gabarit par type de source (checklist numérotée, clauses normatives, système à points, références réglementaires) :

Extraction. Récupérer codes et intitulés depuis le PDF ou le tableur source.

Normalisation. Traduire, nettoyer, harmoniser la formulation.

Rapprochement assisté. Un calcul de similarité sémantique (plongements vectoriels ou modèle de langage) propose le critère commun le plus proche et le degré de rapprochement. Un humain valide ou corrige. C'est l'accélérateur central : il transforme le mapping manuel en revue assistée.

Validation et chargement. Contrôle SHACL, puis écriture dans le triple store, l'export et la base de travail.

Chaque référentiel est versionné. Une nouvelle version d'une norme crée de nouvelles instances reliées à l'ancienne par `dct:isVersionOf`, ce qui trace les évolutions.

## 7. Le profil applicatif et SHACL

Le fichier `profil-shacl.ttl` formalise le contrat d'ingestion. Il exige notamment qu'un référentiel ait un titre, qu'un critère commun ait un libellé et un thème, et qu'un critère de référentiel ait un libellé, dérive d'un référentiel, porte un thème, un niveau, et soit rapproché d'au moins un critère commun. Les shapes valident déjà l'ontologie actuelle : les 881 critères, 9 référentiels et 51 critères communs sont conformes. Le même profil se généralise en remplaçant les classes `flo:` par les classes `std:`.

## 8. Gouvernance et publication

Le socle commun devient un commun numérique gouverné. Trois conditions.

Gestion contrôlée. Une règle claire pour ajouter ou modifier un critère commun, et un versionnement du scheme.

Traçabilité des rapprochements. Chaque mapping porte sa provenance : qui l'a établi, quand, par quelle méthode, avec quelle confiance. Le vocabulaire PROV-O convient.

Publication. IRIs déréférençables sous `ontology.kosm.io`, négociation de contenu (HTML, Turtle, JSON-LD), scheme SKOS publié et citable.

## 9. Connexion aux référentiels mondiaux

Pour ancrer le socle dans l'écosystème, aligner les critères communs sur les cadres existants via `skos:exactMatch` et `skos:closeMatch` : points de données ESRS et CSRD, indicateurs GRI, taxonomie environnementale de l'UE, objectifs de développement durable de l'ONU, et ESCO pour les compétences. Le socle devient alors un point de passage entre référentiels et cadres de reporting, ce qui est la valeur d'un commun.

## 10. Feuille de route

Court terme : valider la taxonomie refondue avec un comité, puis intégrer une première norme ISO hors horticulture (ISO 14001 ou 14064) pour prouver la généricité.

Moyen terme : industrialiser le pipeline avec rapprochement assisté et gestion de versions, puis intégrer GLOBALG.A.P. (et son module GRASP), MPS-GAP et MPS-SQ, Fair Flowers Fair Plants.

Plus tard : publier le socle en commun numérique déréférençable, avec ses alignements ESRS, GRI et ODD, et ouvrir la contribution à d'autres acteurs de filière.

## 11. Fichiers de ce paquet

| Fichier | Contenu |
|---|---|
| `socle-commun-generique.ttl` | Cœur de modèle `std:` et taxonomie SKOS multi-domaine (7 catégories, 13 thèmes, 51 communs migrés, 7 domaines) |
| `profil-shacl.ttl` | Profil applicatif et contraintes SHACL d'ingestion, validant les données actuelles |
| `Architecture_cible_socle_generique.md` | La présente note |

Ces fichiers complètent l'ontologie existante (`../floriscore-referentiels.ttl`) sans la remplacer : le socle générique est la cible vers laquelle migrer, et les liens `skos:exactMatch` assurent la continuité.
