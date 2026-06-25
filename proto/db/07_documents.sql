-- Frameko — proto V1 — Auto-évaluation connectée pilotée par les documents
--
-- Ajoute le mode connecté (Supabase Auth → org via org_member) et le socle
-- « documents → évaluations » :
--   • org_member : appartenance utilisateur Supabase ↔ organisation ;
--   • document   : un fichier importé d'un type donné (evidence_type), avec
--                  date de validité détectée et statut d'analyse IA ;
--   • evaluation : évaluation d'une exigence (framework_criterion) issue d'un
--                  document OU saisie manuellement.
--
-- Isolation : RLS FORCE adossée au GUC `app.current_org_id` (même mécanisme que
-- 03_auth_rls.sql), positionné par l'application après vérification du JWT
-- Supabase et résolution de l'org de l'utilisateur. Idempotent.

-- ── L'org peut être créée côté web (sans jeton MCP) ─────────────────────────
alter table org alter column token_hash drop not null;
alter table org add column if not exists created_by uuid;   -- uid Supabase du créateur

-- ── Appartenance utilisateur ↔ organisation ─────────────────────────────────
create table if not exists org_member (
    id         uuid primary key default gen_random_uuid(),
    org_id     uuid not null references org(id) on delete cascade,
    user_id    uuid not null,                       -- uid Supabase (auth.users.id)
    email      text,
    role       text not null default 'member' check (role in ('owner', 'member')),
    created_at timestamptz default now(),
    unique (org_id, user_id)
);
create index if not exists idx_org_member_user on org_member(user_id);
create index if not exists idx_org_member_org  on org_member(org_id);

-- ── Documents importés ──────────────────────────────────────────────────────
create table if not exists document (
    id               uuid primary key default gen_random_uuid(),
    org_id           uuid not null references org(id) on delete cascade,
    evidence_type_id uuid not null references evidence_type(id),   -- le « type de document »
    filename         text not null,
    storage_key      text not null,                  -- chemin objet Supabase Storage
    mime             text,
    size_bytes       bigint,
    uploaded_by      uuid,                            -- uid Supabase
    uploaded_at      timestamptz default now(),
    valid_until      date,                            -- date de validité détectée (nullable)
    extracted_text   text,                            -- cache du texte extrait (ré-éval/audit)
    analysis_status  text not null default 'pending'
                     check (analysis_status in ('pending', 'running', 'done', 'error')),
    analysis_error   text,
    created_at       timestamptz default now()
);
create index if not exists idx_document_org  on document(org_id);
create index if not exists idx_document_type on document(evidence_type_id);

-- ── Évaluations d'exigences (par document ou manuelles) ─────────────────────
create table if not exists evaluation (
    id                     uuid primary key default gen_random_uuid(),
    org_id                 uuid not null references org(id) on delete cascade,
    framework_criterion_id uuid not null references framework_criterion(id),
    status                 text not null
                           check (status in ('conforme', 'partiel', 'non_conforme', 'non_applicable')),
    interpretation         text,                      -- raisonnement IA ou note manuelle
    source                 text not null check (source in ('document', 'manual')),
    document_id            uuid references document(id) on delete cascade,  -- null si manuel
    confidence             numeric,                   -- score IA (nullable)
    created_at             timestamptz default now(),
    updated_at             timestamptz default now()
);
create index if not exists idx_evaluation_org      on evaluation(org_id);
create index if not exists idx_evaluation_crit     on evaluation(org_id, framework_criterion_id);
create index if not exists idx_evaluation_document on evaluation(document_id);

-- ── Droits du rôle applicatif (sans BYPASSRLS) ──────────────────────────────
grant select on evidence_type, criterion_evidence to frameko_app;
grant select, insert, update, delete on org_member, document, evaluation to frameko_app;

-- ── Row-Level Security (FORCE) adossée à app.current_org_id ──────────────────
do $$
declare t text;
begin
    foreach t in array array['org_member', 'document', 'evaluation'] loop
        execute format('alter table %I enable row level security', t);
        execute format('alter table %I force  row level security', t);
        execute format('drop policy if exists org_isolation on %I', t);
        execute format(
            'create policy org_isolation on %I '
            'using (org_id::text = current_setting(''app.current_org_id'', true)) '
            'with check (org_id::text = current_setting(''app.current_org_id'', true))', t);
    end loop;
end $$;
