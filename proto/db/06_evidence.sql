-- Frameko — proto V1 — Types de preuves (CCCEV : cccev:EvidenceType / cccev:Evidence)
--
-- Lie chaque critère de référentiel au(x) TYPE(S) de preuve attendu(s) (moyen de
-- vérification). Catalogue canonique réutilisable entre critères et référentiels.
-- Source initiale : checklist FlorEcuador V4.0 (colonne « CRITERIO DE CUMPLIMIENTO »).
-- Idempotent.

drop table if exists criterion_evidence cascade;
drop table if exists evidence_type cascade;

-- Catalogue des types de preuves (canonique, partagé)
create table evidence_type (
    id       uuid primary key default gen_random_uuid(),
    slug     text unique not null,
    label_fr text not null
);

-- Lien M:N critère ↔ type de preuve, + le texte verbatim du moyen de vérification.
create table criterion_evidence (
    id                     uuid primary key default gen_random_uuid(),
    framework_criterion_id uuid not null references framework_criterion(id) on delete cascade,
    evidence_type_id       uuid not null references evidence_type(id),
    detail                 text,                       -- moyen de vérification (verbatim source)
    unique (framework_criterion_id, evidence_type_id)
);

create index idx_ce_criterion on criterion_evidence(framework_criterion_id);
create index idx_ce_type on criterion_evidence(evidence_type_id);

insert into evidence_type (slug, label_fr) values
('document',      'Document / procédure'),
('registre',      'Registre / enregistrement'),
('plan-carte',    'Plan / carte / schéma'),
('certificat',    'Certificat / homologation'),
('analyse',       'Analyse / rapport technique'),
('photo',         'Photo / preuve visuelle'),
('contrat',       'Contrat / accord écrit'),
('formation',     'Formation / attestation'),
('inspection',    'Constat sur site / inspection'),
('signalisation', 'Signalisation / étiquetage'),
('facture',       'Facture / preuve d''achat'),
('autre',         'Autre');
