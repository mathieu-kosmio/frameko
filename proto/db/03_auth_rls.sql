-- Frameko — proto V1 — Auth & isolation des auto-évaluations (RLS)
--
-- Les auto-évaluations sont des données sensibles (RGPD) : chaque organisation
-- ne doit voir que les siennes. L'isolation est garantie au niveau de la base
-- par Row-Level Security en mode FORCE (s'applique même au propriétaire des
-- tables), avec une politique adossée au GUC de session `app.current_org_id`
-- que l'application positionne par requête (SET LOCAL) après authentification.
--
-- Migration NON destructive du socle : ne touche qu'aux tables d'évaluation
-- (transitoires) et ajoute la table org.

-- ── Organisations ───────────────────────────────────────────────────────────
create table if not exists org (
    id         uuid primary key default gen_random_uuid(),
    slug       text unique not null,
    name       text not null,
    token_hash text unique not null,           -- sha256 d'un jeton opaque
    created_at timestamptz default now()
);

-- ── Rattachement des évaluations à une organisation ─────────────────────────
-- Les évaluations existantes sont transitoires (proto) : on repart propre.
truncate assessment_answer, assessment restart identity cascade;

alter table assessment add column if not exists org_id uuid references org(id) on delete cascade;
alter table assessment alter column org_id set not null;

create index if not exists idx_assessment_org on assessment(org_id);

-- ── Rôle applicatif sans BYPASSRLS ──────────────────────────────────────────
-- Le rôle Supabase `postgres` possède BYPASSRLS : il contourne toute policy,
-- même en mode FORCE. L'application se connecte donc, pour les opérations
-- d'auto-évaluation, via un rôle dédié `frameko_app` SANS ce privilège, pour
-- lequel la RLS s'applique réellement. Ce rôle est créé ici (NOLOGIN, à
-- moindre privilège) ; son mot de passe LOGIN et l'APP_DATABASE_URL sont
-- provisionnés hors SQL par scripts/setup_app_role.py (secret hors dépôt).
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'frameko_app') then
        create role frameko_app nologin;
    end if;
end $$;

grant usage on schema public to frameko_app;
grant select on domain, category, theme, common_criterion, framework, framework_criterion to frameko_app;
grant select, insert, update, delete on assessment, assessment_answer to frameko_app;

-- ── Row-Level Security ──────────────────────────────────────────────────────
alter table assessment        enable row level security;
alter table assessment        force  row level security;
alter table assessment_answer enable row level security;
alter table assessment_answer force  row level security;

-- assessment : visible/insérable seulement pour l'org du GUC courant.
drop policy if exists org_isolation on assessment;
create policy org_isolation on assessment
    using      (org_id::text = current_setting('app.current_org_id', true))
    with check (org_id::text = current_setting('app.current_org_id', true));

-- assessment_answer : rattaché à une évaluation visible (donc même org).
-- La sous-requête est elle-même soumise à la RLS de `assessment` (FORCE),
-- ce qui restreint aux évaluations de l'org courant.
drop policy if exists org_isolation_answer on assessment_answer;
create policy org_isolation_answer on assessment_answer
    using      (exists (select 1 from assessment a where a.id = assessment_answer.assessment_id))
    with check (exists (select 1 from assessment a where a.id = assessment_answer.assessment_id));
