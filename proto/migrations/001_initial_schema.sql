-- Frameko — Schéma initial Postgres/Supabase
-- Migration 001 — 2026-06-23

-- Extension vectorielle (pgvector)
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Taxonomie ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS domain (
    id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text UNIQUE NOT NULL,
    label_fr text NOT NULL,
    label_en text
);

CREATE TABLE IF NOT EXISTS category (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug      text UNIQUE NOT NULL,
    label_fr  text NOT NULL,
    label_en  text,
    domain_id uuid REFERENCES domain(id)
);

CREATE TABLE IF NOT EXISTS theme (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text UNIQUE NOT NULL,
    label_fr    text NOT NULL,
    label_en    text,
    category_id uuid REFERENCES category(id)
);

-- ── Licences ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS license (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    holder          text NOT NULL,
    scope           text,
    allows_verbatim boolean DEFAULT true,
    terms_url       text
);

-- ── Critères communs ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS common_criterion (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code       text UNIQUE NOT NULL,
    label_fr   text NOT NULL,
    label_en   text,
    definition text,
    theme_id   uuid REFERENCES theme(id),
    embedding  vector(1536),
    iri        text UNIQUE,
    weight     numeric DEFAULT 1.0,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_common_criterion_theme ON common_criterion(theme_id);
CREATE INDEX IF NOT EXISTS idx_common_criterion_embed
    ON common_criterion USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- ── Référentiels ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS framework (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         text UNIQUE NOT NULL,
    title        text NOT NULL,
    publisher    text,
    version      text,
    domain_id    uuid REFERENCES domain(id),
    type         text,                -- 'label', 'standard', 'norme', 'charte'
    jurisdiction text,
    language     text DEFAULT 'fr',
    license_id   uuid REFERENCES license(id),
    status       text DEFAULT 'active',
    iri          text UNIQUE,
    created_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS framework_version (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    framework_id uuid REFERENCES framework(id) ON DELETE CASCADE,
    version      text NOT NULL,
    valid_from   date,
    supersedes_id uuid REFERENCES framework_version(id)
);

-- ── Critères de référentiel ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS framework_criterion (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    framework_id         uuid REFERENCES framework(id) ON DELETE CASCADE NOT NULL,
    reference            text,
    label                text NOT NULL,
    theme_id             uuid REFERENCES theme(id),
    level                text,       -- 'major', 'intermediate', 'minor'
    embedding            vector(1536),
    iri                  text UNIQUE,
    source_excerpt       text,
    is_verbatim_allowed  boolean DEFAULT true,
    created_at           timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fc_framework ON framework_criterion(framework_id);
CREATE INDEX IF NOT EXISTS idx_fc_theme     ON framework_criterion(theme_id);
CREATE INDEX IF NOT EXISTS idx_fc_embed
    ON framework_criterion USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── Mappings (rapprochements) ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mapping (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    framework_criterion_id  uuid REFERENCES framework_criterion(id) ON DELETE CASCADE NOT NULL,
    common_criterion_id     uuid REFERENCES common_criterion(id) ON DELETE CASCADE NOT NULL,
    degree                  text NOT NULL CHECK (degree IN (
                                'equivautA', 'plusStrictQue', 'plusLargeQue', 'rapprocheDe'
                            )),
    confidence              numeric DEFAULT 1.0,
    method                  text DEFAULT 'manual',  -- 'manual', 'llm', 'vector'
    validated_by            uuid,
    validated_at            timestamptz,
    UNIQUE (framework_criterion_id, common_criterion_id)
);

CREATE INDEX IF NOT EXISTS idx_mapping_cc ON mapping(common_criterion_id);
CREATE INDEX IF NOT EXISTS idx_mapping_fc ON mapping(framework_criterion_id);

-- ── Types de preuves ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evidence_type (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label       text NOT NULL,
    description text
);

CREATE TABLE IF NOT EXISTS criterion_evidence (
    framework_criterion_id uuid REFERENCES framework_criterion(id) ON DELETE CASCADE,
    evidence_type_id       uuid REFERENCES evidence_type(id) ON DELETE CASCADE,
    PRIMARY KEY (framework_criterion_id, evidence_type_id)
);

-- ── Organisations et utilisateurs ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS org (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_user (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     uuid REFERENCES org(id),
    role       text DEFAULT 'viewer',   -- 'viewer', 'curator', 'admin'
    email      text UNIQUE,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_key (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid REFERENCES app_user(id) ON DELETE CASCADE,
    key_hash   text UNIQUE NOT NULL,
    name       text,
    expires_at timestamptz,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entitlement (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    consumer_id  uuid REFERENCES app_user(id) ON DELETE CASCADE,
    framework_id uuid REFERENCES framework(id) ON DELETE CASCADE,
    scope        text DEFAULT 'summary',  -- 'summary' ou 'verbatim'
    expires_at   timestamptz,
    UNIQUE (consumer_id, framework_id)
);

-- ── Auto-évaluation (S3) ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS assessment (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid REFERENCES org(id) ON DELETE CASCADE NOT NULL,
    framework_id uuid REFERENCES framework(id) ON DELETE CASCADE NOT NULL,
    status       text DEFAULT 'in_progress',
    score        numeric,
    created_at   timestamptz DEFAULT now(),
    updated_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS assessment_answer (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id       uuid REFERENCES assessment(id) ON DELETE CASCADE NOT NULL,
    common_criterion_id uuid REFERENCES common_criterion(id) ON DELETE CASCADE NOT NULL,
    status              text DEFAULT 'pending' CHECK (status IN (
                            'compliant', 'partial', 'non_compliant', 'not_applicable', 'pending'
                        )),
    note                text,
    evidence_url        text,
    created_at          timestamptz DEFAULT now(),
    UNIQUE (assessment_id, common_criterion_id)
);

-- ── Ingestion ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingestion_job (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_ref   text NOT NULL,
    type         text,   -- 'pdf', 'spreadsheet', 'url', 'rdf'
    status       text DEFAULT 'pending' CHECK (status IN (
                     'pending', 'processing', 'awaiting_validation', 'completed', 'failed'
                 )),
    log          jsonb DEFAULT '[]',
    framework_id uuid REFERENCES framework(id),
    created_at   timestamptz DEFAULT now(),
    updated_at   timestamptz DEFAULT now()
);

-- ── Provenance ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS provenance (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_iri text,
    actor       text,
    method      text,
    confidence  numeric,
    ts          timestamptz DEFAULT now()
);

-- ── Row Level Security (Supabase) ──────────────────────────────────────────

ALTER TABLE assessment ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_answer ENABLE ROW LEVEL SECURITY;
ALTER TABLE entitlement ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_key ENABLE ROW LEVEL SECURITY;

-- Politique : une organisation ne voit que ses propres évaluations
CREATE POLICY assessment_org_isolation ON assessment
    USING (org_id = (SELECT org_id FROM app_user WHERE id = auth.uid()));

CREATE POLICY assessment_answer_org_isolation ON assessment_answer
    USING (assessment_id IN (
        SELECT id FROM assessment WHERE org_id = (
            SELECT org_id FROM app_user WHERE id = auth.uid()
        )
    ));
