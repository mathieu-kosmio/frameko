# Frameko

**Plateforme d'agrégation de référentiels de certification** — Kosmio / Certifiko

Frameko héberge une ontologie de référentiels (labels, normes, chartes) alignée sur [CCCEV](https://joinup.ec.europa.eu/collection/semantic-interoperability-community-semic/solution/core-criterion-and-core-evidence-vocabulary), l'alimente par ingestion assistée LLM, et expose la connaissance via une API REST et un serveur MCP.

## Structure

```
ONTOLOGIE/          Ontologie RDF (Turtle, SHACL, exports CSV)
proto/              Prototype applicatif (FastAPI + Supabase + MCP)
```

## Liens

- [Spécification plateforme](ONTOLOGIE/application/Specification_plateforme_referentiels.md)
- [Ontologie CCCEV](ONTOLOGIE/Ontologie_referentiels_CCCEV.md)
- [Architecture cible](ONTOLOGIE/socle-generique/Architecture_cible_socle_generique.md)

## Statut

V0.1 — prototype (juin 2026). Ontologie : 9 référentiels horticoles, 51 critères communs, 876 mappings qualifiés.
