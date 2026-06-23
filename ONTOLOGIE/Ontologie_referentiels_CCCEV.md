# Ontologie des référentiels horticoles alignée sur CCCEV

**Projet** : Floriscore (Kosmio)
**Version** : 1.1.0 (23 juin 2026)
**Standard de référence** : Core Criterion and Core Evidence Vocabulary (CCCEV) 2.2.0, SEMIC
**Namespace** : `https://ontology.kosm.io/floriscore/ref#` (préfixe `flo:`)
**Fichier ontologie** : `floriscore-referentiels.ttl` (RDF/Turtle, 6603 triples, validé rdflib)

## En une phrase

Cette ontologie place neuf référentiels de certification horticole dans un cadre sémantique commun, conserve chaque label intact, et relie tous leurs critères à un socle partagé de 51 critères communs pour permettre la comparaison critère par critère.

## 1. Couverture actuelle

Neuf référentiels alignés, 13 thèmes, 51 critères communs, 876 critères de référentiel traduits en français et rattachés individuellement.

| Référentiel | Éditeur | Critères | Portée |
|---|---|---|---|
| Florverde Sustainable Flowers (FSF) V7.1.3 | Asocolflores | 225 | Colombie / international |
| FlorEcuador Certified V4.0 | Expoflores | 195 | Équateur |
| On the way to PlanetProof (Produits végétaux) | SMK | 194 | Pays-Bas / international |
| VivaiFiori | Associazione Vivaisti Italiani | 71 | Italie |
| Rainforest Alliance V1.4 | Rainforest Alliance | 70 | International |
| Fairtrade Flowers and Plants | Fairtrade International | 52 | International |
| MPS-ABC | MPS (My-MPS) | 29 | Pays-Bas / international |
| Plante Bleue Niveau 3 | VALHOR | 23 | France |
| Charte Qualité Fleurs | VALHOR | 17 | France |

Chaque critère est rattaché au critère commun le plus proche. Dans la base Notion, regrouper « Critères de référentiel » par « Critère commun » fait apparaître côte à côte les exigences équivalentes des neuf labels. Export tabulaire complet : `export_tous_criteres.csv` (876 lignes).

## 2. Objectif

L'ontologie répond à deux exigences tenues ensemble.

D'abord, conserver chaque référentiel global et intact. Chaque label garde ses chapitres, ses critères propres, ses niveaux d'exigence et sa référence d'origine, avec sa formulation.

Ensuite, rapprocher les critères similaires. Une couche de critères communs thématiques sert de socle canonique. Les critères de référentiels différents qui visent la même exigence pointent vers un même critère commun, ce qui matérialise leur similarité tout en préservant les spécificités de chacun.

Ce double mouvement constitue le cœur de valeur de Floriscore : comparer, scorer et croiser des labels qui décrivent les mêmes réalités avec des mots et des structures différents.

## 3. Pourquoi CCCEV

CCCEV est le vocabulaire européen (SEMIC) conçu pour échanger des informations entre une partie qui définit des exigences (`Requirement`) et une partie qui y répond par des preuves (`Evidence`). Sa spécialisation `Criterion` désigne une exigence formulée dans une logique d'évaluation. C'est exactement la nature d'un critère de label.

Ce choix apporte un socle normatif maintenu par l'UE et réutilisé par l'eProcurement Ontology et les data spaces, une séparation nette entre l'exigence et sa preuve, et une extensibilité native par sous-classement qui permet d'ajouter la couche de rapprochement tout en restant conforme au standard.

### Classes CCCEV mobilisées

| Classe CCCEV (`http://data.europa.eu/m8g/`) | Usage Floriscore |
|---|---|
| `Requirement` | Chapitre ou regroupement de critères |
| `Criterion` (sous-classe de Requirement) | Critère de référentiel et critère commun |
| `Constraint` | Seuils chiffrés (extension future) |
| `ReferenceFramework` | Le référentiel / label lui-même |
| `Evidence` | Preuve fournie par l'exploitant |
| `EvidenceType` | Type de preuve attendue (registre, audit, fiche) |
| `SupportedValue` | Réponse chiffrée d'un audit (extension future) |

Propriétés CCCEV réutilisées : `hasConcept`, `hasRequirement`, `isDerivedFrom`, `supportsRequirement`, `weight`.

## 4. Comment fonctionne l'ontologie

### 4.1 Les classes de l'extension

| Classe `flo:` | Sous-classe de | Rôle |
|---|---|---|
| `Referentiel` | `cccev:ReferenceFramework` | Le label ou standard, conservé global |
| `Chapitre` | `cccev:Requirement` | Regroupement interne à un référentiel |
| `CritereReferentiel` | `cccev:Criterion` | Critère tel que formulé par un référentiel |
| `CritereCommun` | `cccev:Criterion`, `skos:Concept` | Critère canonique, socle de rapprochement |
| `Theme` | `skos:Concept` | Axe thématique de la grille commune |
| `NiveauExigence` | `skos:Concept` | Statut du critère (majeur, intermédiaire, mineur) |
| `TypePreuve` | `cccev:EvidenceType` | Type de preuve attendu |
| `Preuve` | `cccev:Evidence` | Preuve concrète fournie |

### 4.2 La couche de rapprochement

Le rapprochement repose sur des relations qui spécialisent à la fois `flo:aligneSur` et les relations de correspondance SKOS, ce qui garantit une sémantique standard et un degré explicite.

| Propriété `flo:` | Sous-propriété de | Sens |
|---|---|---|
| `aligneSur` | `skos:mappingRelation` | Rapprochement générique (degré non précisé) |
| `equivautA` | `aligneSur`, `skos:exactMatch` | Exigence couverte à l'identique |
| `rapprocheDe` | `aligneSur`, `skos:closeMatch` | Exigences proches |
| `plusLargeQue` | `aligneSur`, `skos:broadMatch` | Le critère couvre un périmètre plus large |
| `plusStrictQue` | `aligneSur`, `skos:narrowMatch` | Le critère est plus exigeant que le commun |

Cette modélisation préserve l'information. Les critères ne sont pas fusionnés, leur relation et son intensité sont déclarées. Un audit peut donc remonter du critère commun vers chaque formulation d'origine, et inversement.

Les 876 critères sont qualifiés : chacun porte une des quatre relations ci-dessus, sur tous les thèmes. Plus aucun `flo:aligneSur` générique ne subsiste.

| Degré | Critères | Part |
|---|---|---|
| `plusStrictQue` (plus précis que le commun) | 483 | 55 % |
| `rapprocheDe` (proche) | 184 | 21 % |
| `equivautA` (équivalent) | 180 | 21 % |
| `plusLargeQue` (plus large que le commun) | 29 | 3 % |

La prédominance de `plusStrictQue` traduit une réalité du corpus : un critère de label est en général une exigence opérationnelle plus fine que le concept thématique du critère commun.

**Méthodologie de qualification (v1, à valider par expert)** : pour chaque critère, le degré est déduit par une règle reproductible combinant le recouvrement lexical entre le libellé du critère et celui du critère commun (correspondance par racines) et la granularité du critère (profondeur du code de référence). Recouvrement fort vers équivalence, libellé multi-domaines vers `plusLargeQue`, item fin et spécifique vers `plusStrictQue`, recouvrement partiel vers `rapprocheDe`. La règle fournit une première qualification homogène et auditable ; elle est destinée à être affinée à dire d'expert thème par thème, en priorité sur les recoupements à enjeu (équivalences exactes pour la reconnaissance mutuelle).

### 4.3 La grille thématique commune

Treize thèmes structurent la grille (`skos:ConceptScheme` `flo:GrilleCommune`) : gouvernance et système de gestion, droit du travail et conditions sociales, formation et bien-être, santé et sécurité au travail, gestion et conservation de l'eau, sols substrats et fertilisation, contrôle phytosanitaire et usage des pesticides, gestion des déchets, paysage et biodiversité, énergie maintenance et empreinte carbone, origine du matériel végétal et intrants, qualité et post-récolte, traçabilité registres et transparence.

### 4.4 Les niveaux d'exigence

Trois niveaux normalisent la criticité hétérogène des labels : Niveau 1 (majeur / obligatoire), Niveau 2 (intermédiaire), Niveau 3 (mineur). Chaque référentiel utilise son propre vocabulaire (majeur/mineur, critical major, écart majeur, schéma de points), ramené à cette échelle commune.

### 4.5 Comment un critère est modélisé

Exemple instancié en Turtle.

```turtle
flo:pp-2-1 a flo:CritereReferentiel ;
    flo:reference "2.1" ;
    skos:prefLabel "Plan d'action pour la lutte intégrée des cultures (LIC)"@fr ;
    cccev:isDerivedFrom flo:planetproof ;
    flo:aPourTheme flo:thm-phyto ;
    flo:aNiveauExigence flo:niv-majeur ;
    flo:aligneSur flo:cc-manejo-integrado-de-plagas-mip .
```

Le critère reste rattaché à son référentiel par `cccev:isDerivedFrom`, classé par thème et par niveau, et relié au critère commun « Lutte intégrée contre les ravageurs (MIP) ». Le même critère commun reçoit les critères équivalents de Florverde, FlorEcuador, VivaiFiori, etc.

### 4.6 Réutilisation de vocabulaires standards

CCCEV pour le socle (critères, preuves, cadre de référence). SKOS pour les critères communs, thèmes, niveaux et relations de correspondance. DCAT et DCT pour les métadonnées des référentiels. ADMS pour le statut. ORG et FOAF pour les organismes émetteurs. VANN pour les métadonnées de l'ontologie.

## 5. Usages possibles

**Comparer les labels critère par critère.** En regroupant les critères de référentiel par critère commun, on visualise quelles exigences sont partagées, lesquelles sont propres à un label, et où se situent les différences de formulation ou de niveau.

**Analyser la couverture thématique.** Croiser thème et référentiel montre les forces et les angles morts de chaque label (par exemple PlanetProof très dense sur l'énergie et la biodiversité, Charte Qualité Fleurs centrée sur la qualité produit et le volet social).

**Construire un score Floriscore.** La propriété `flo:scoreFloriscore` (sous-propriété de `cccev:weight`) permet de pondérer chaque critère commun et de calculer un score comparable entre exploitations, indépendamment du label d'origine.

**Établir des équivalences pour la reconnaissance mutuelle.** Les relations `equivautA` et `plusStrictQue` documentent quels critères d'un label en couvrent un autre, ce qui soutient les démarches de double certification ou de reconnaissance entre filières.

**Alimenter un data space ou un commun numérique.** Le fichier Turtle est exploitable par n'importe quel triple store ou moteur SPARQL et reste conforme à CCCEV, donc interopérable avec l'écosystème européen des données.

**Servir de base à une interface de saisie ou d'audit.** La séparation critère / preuve permet de générer des grilles d'audit où chaque exigence appelle un type de preuve attendu.

## 6. Prochains référentiels à intégrer

L'architecture accepte un nouveau référentiel sans modification du modèle : il suffit de déclarer le `flo:Referentiel`, de créer ses `flo:CritereReferentiel` et de les rattacher aux critères communs existants, ou d'enrichir la grille si une exigence nouvelle apparaît.

Candidats pertinents pour la filière ornementale et horticole :

- **GLOBALG.A.P. (Flowers and Ornamentals, module GRASP)**, très répandu à l'international, complémentaire sur la sécurité des process et le volet social.
- **GLOBALG.A.P. Chain of Custody**, pour la traçabilité aval.
- **MPS-GAP et MPS-SQ (Socially Qualified)**, qui prolongent MPS-ABC sur les bonnes pratiques agricoles et le social.
- **Fair Flowers Fair Plants (FFP)**, label européen de durabilité florale.
- **Fairtrade Hired Labour Standard**, pour le détail des exigences de travail salarié.
- **Référentiel HVE (Haute Valeur Environnementale)**, déjà cité par Plante Bleue, qui mériterait une instanciation propre pour expliciter les items référencés.
- **Florverde et Rainforest dans leurs versions sectorielles mises à jour.**
- **Ecocert et labels bio ornementaux** selon les marchés visés.

Pour chaque ajout : extraire les critères, traduire en français, rattacher finement aux 51 critères communs, charger dans Notion et propager dans le fichier Turtle. Le pipeline est désormais rodé sur neuf référentiels.

## 7. Gouvernance et suite

Les vocabulaires contrôlés (grille commune, thèmes, niveaux) sont des `skos:ConceptScheme` versionnés, à faire valider par un comité filière. L'étape suivante consiste à ajouter des contraintes SHACL (cardinalités, listes de valeurs) pour fiabiliser la saisie, et à exploiter `cccev:Constraint` pour les seuils chiffrés (heures, distances, doses). La qualification des degrés de rapprochement est faite en version 1 (règle reproductible). Le travail restant est sa revue à dire d'expert, thème par thème, en se concentrant d'abord sur les `equivautA` candidats qui fondent la reconnaissance mutuelle entre labels.

## 8. Fichiers livrables

| Fichier | Contenu |
|---|---|
| `floriscore-referentiels.ttl` | Ontologie RDF complète (modèle plus 9 référentiels instanciés) |
| `Ontologie_referentiels_CCCEV.md` | La présente documentation |
| `schema_ontologie.png` / `.svg` | Schéma visuel du modèle |
| `export_tous_criteres.csv` | Les 876 critères (référentiel, code, libellé, thème, niveau, critère commun, degré de rapprochement) |
| `export_referentiels.csv` | Les 9 référentiels et leurs métadonnées |
| `export_criteres_communs.csv` | Les 51 critères communs |
| `export_themes.csv` | Les 13 thèmes |
| Base Notion « Critères de référentiel » | Version exploitable et filtrable, reliée aux critères communs |

## Sources

- [Core Criterion and Core Evidence Vocabulary (CCCEV) 2.2.0, SEMIC](https://semiceu.github.io/CCCEV/releases/2.2.0/)
- [CCCEV, Interoperable Europe Portal](https://interoperable-europe.ec.europa.eu/collection/semic-support-centre/solution/core-criterion-and-core-evidence-vocabulary)
- Sources internes du dossier : Florverde FSF V7.1.3, FlorEcuador V4.0, On the way to PlanetProof (Produits végétaux), VivaiFiori (Disciplinare), Rainforest Alliance Sustainable Agriculture Standard V1.4, Fairtrade Flowers and Plants Standard, MPS-ABC (Programme de certification), Plante Bleue Niveau 3, Charte Qualité Fleurs (Septembre 2024).
