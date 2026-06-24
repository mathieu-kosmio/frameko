-- Frameko — proto V1 — Schéma de la base de connaissance
-- Postgres 17 + pgvector. Embeddings locaux 384 dimensions
-- (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
--
-- Idempotent : on repart d'un état propre à chaque application (proto).

create extension if not exists vector;

drop table if exists assessment_answer cascade;
drop table if exists assessment cascade;
drop table if exists framework_criterion cascade;
drop table if exists framework cascade;
drop table if exists common_criterion cascade;
drop table if exists theme cascade;
drop table if exists category cascade;
drop table if exists domain cascade;

-- ── Taxonomie du socle (3 niveaux : domaine ▸ catégorie ▸ thème) ────────────

create table domain (
    id       uuid primary key default gen_random_uuid(),
    slug     text unique not null,
    label_fr text not null,
    label_en text
);

create table category (
    id          uuid primary key default gen_random_uuid(),
    slug        text unique not null,
    label_fr    text not null,
    label_en    text,
    domain_slug text references domain(slug)
);

create table theme (
    id            uuid primary key default gen_random_uuid(),
    slug          text unique not null,
    label_fr      text not null,
    label_en      text,
    category_slug text references category(slug)
);

-- ── Socle commun : 51 critères canoniques ───────────────────────────────────

create table common_criterion (
    id         uuid primary key default gen_random_uuid(),
    code       text unique not null,            -- ex. c-001
    label_fr   text not null,                   -- skos:prefLabel @fr (clé de jointure CSV)
    theme_slug text references theme(slug),
    embedding  vector(384)
);

-- ── Référentiels et leurs critères ──────────────────────────────────────────

create table framework (
    id        uuid primary key default gen_random_uuid(),
    slug      text unique not null,
    title     text not null,
    publisher text,
    version   text,
    coverage  text,
    status    text default 'actif'
);

create table framework_criterion (
    id                  uuid primary key default gen_random_uuid(),
    framework_slug      text not null references framework(slug),
    reference           text,
    label               text not null,
    theme_slug          text references theme(slug),       -- déduit du critère commun
    level               text,                              -- Niveau 1 (majeur) | Niveau 2 | Niveau 3 (mineur)
    degree              text not null check (degree in (
                            'equivautA', 'plusStrictQue', 'plusLargeQue', 'rapprocheDe'
                        )),
    common_criterion_id uuid not null references common_criterion(id),
    embedding           vector(384)
);

-- ── Auto-évaluation de conformité (S3) ──────────────────────────────────────

create table assessment (
    id             uuid primary key default gen_random_uuid(),
    framework_slug text not null references framework(slug),
    status         text default 'in_progress',
    created_at     timestamptz default now()
);

create table assessment_answer (
    id                  uuid primary key default gen_random_uuid(),
    assessment_id       uuid not null references assessment(id) on delete cascade,
    common_criterion_id uuid not null references common_criterion(id),
    status              text not null check (status in (
                            'conforme', 'partiel', 'non_conforme', 'non_applicable'
                        )),
    note                text,
    unique (assessment_id, common_criterion_id)
);

-- ── Index ───────────────────────────────────────────────────────────────────

create index idx_category_domain   on category(domain_slug);
create index idx_theme_category     on theme(category_slug);
create index idx_cc_theme           on common_criterion(theme_slug);
create index idx_fc_framework       on framework_criterion(framework_slug);
create index idx_fc_theme           on framework_criterion(theme_slug);
create index idx_fc_common          on framework_criterion(common_criterion_id);
create index idx_aa_assessment      on assessment_answer(assessment_id);

-- Index vectoriels HNSW (cosinus) — pgvector 0.8, pas besoin de pré-remplir
create index idx_cc_embedding on common_criterion
    using hnsw (embedding vector_cosine_ops);
create index idx_fc_embedding on framework_criterion
    using hnsw (embedding vector_cosine_ops);
