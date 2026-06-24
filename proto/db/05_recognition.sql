-- Frameko — proto V1 — Couche de reconnaissance / équivalence (FSI)
--
-- FSI (Floriculture Sustainability Initiative) n'est PAS un référentiel de
-- critères : c'est un « Basket of Standards » qui RECONNAÎT d'autres standards,
-- pilier par pilier (GAP / Environmental / Social). On le modélise donc comme
-- une couche d'équivalence au-dessus des référentiels, pas comme des critères.
--
-- Deux standards reconnus dans le même pilier sont « équivalents » au sens du
-- marché (acceptés de façon interchangeable), ce qui complète le rapprochement
-- critère-par-critère du socle commun.
--
-- Source du panier : https://www.fsi2030.com/basket/ (documentation 2024-2025).
-- Idempotent.

drop table if exists recognition cascade;
drop table if exists recognition_scheme cascade;

create table recognition_scheme (
    slug        text primary key,
    name        text not null,
    description text,
    url         text
);

create table recognition (
    id              uuid primary key default gen_random_uuid(),
    scheme_slug     text not null references recognition_scheme(slug),
    pillar          text not null check (pillar in ('GAP', 'Environmental', 'Social')),
    framework_label text not null,                          -- nom tel que dans le panier
    framework_slug  text references framework(slug),        -- non null si présent dans notre base
    status          text not null default 'recognized'      -- recognized | temporary
        check (status in ('recognized', 'temporary'))
);

create index idx_recognition_scheme on recognition(scheme_slug);
create index idx_recognition_fw on recognition(framework_slug);

insert into recognition_scheme (slug, name, description, url) values
('fsi', 'Floriculture Sustainability Initiative (FSI 2030)',
 'Initiative de marché qui reconnaît (benchmarke) des standards de durabilité floricole par pilier, sans définir ses propres critères de production.',
 'https://www.fsi2030.com/basket/');

-- Panier FSI : (pilier, libellé du standard, slug si en base, statut).
insert into recognition (scheme_slug, pillar, framework_label, framework_slug, status) values
-- ── Pilier GAP ──────────────────────────────────────────────────────────────
('fsi', 'GAP', 'EHPEA Code of Practice',                NULL,                  'temporary'),
('fsi', 'GAP', 'EU Organic Farming',                    NULL,                  'recognized'),
('fsi', 'GAP', 'Florverde Sustainable Flowers',         'florverde',           'recognized'),
('fsi', 'GAP', 'FloriCompact',                          NULL,                  'recognized'),
('fsi', 'GAP', 'GLOBALG.A.P. Floriculture',             'globalgap-fo',        'recognized'),
('fsi', 'GAP', 'Kenya Flower Council (KFC) Silver',     NULL,                  'recognized'),
('fsi', 'GAP', 'MPS-Compact',                           NULL,                  'recognized'),
('fsi', 'GAP', 'MPS-GAP',                               'mps-gap',             'recognized'),
('fsi', 'GAP', 'OHAS Grower Standard',                  NULL,                  'recognized'),
('fsi', 'GAP', 'USDA National Organic Program',         NULL,                  'recognized'),
-- ── Pilier Environmental ────────────────────────────────────────────────────
('fsi', 'Environmental', 'FloriCompact',                NULL,                  'recognized'),
('fsi', 'Environmental', 'Florverde Sustainable Flowers','florverde',          'recognized'),
('fsi', 'Environmental', 'GLOBALG.A.P. IDA Module',     NULL,                  'recognized'),
('fsi', 'Environmental', 'Kenya Flower Council (KFC) Silver', NULL,            'recognized'),
('fsi', 'Environmental', 'MPS-ABC',                     'mps-abc',             'recognized'),
('fsi', 'Environmental', 'MPS-Compact',                 NULL,                  'recognized'),
('fsi', 'Environmental', 'MPS-GAP',                     'mps-gap',             'recognized'),
('fsi', 'Environmental', 'MPS-SQ',                      'mps-sq',              'recognized'),
('fsi', 'Environmental', 'SIZA Environmental',          NULL,                  'recognized'),
-- ── Pilier Social ───────────────────────────────────────────────────────────
('fsi', 'Social', 'Amfori BSCI Code',                   NULL,                  'recognized'),
('fsi', 'Social', 'EHPEA Code of Practice',             NULL,                  'temporary'),
('fsi', 'Social', 'ETI Base Code / SMETA',              NULL,                  'recognized'),
('fsi', 'Social', 'Fairtrade Hired Labour',             'fairtrade',           'temporary'),
('fsi', 'Social', 'Florverde Sustainable Flowers',      'florverde',           'recognized'),
('fsi', 'Social', 'Kenya Flower Council (KFC) Silver',  NULL,                  'recognized'),
('fsi', 'Social', 'MPS-SQ',                             'mps-sq',              'recognized'),
('fsi', 'Social', 'Rainforest Alliance',                'rainforest-alliance', 'recognized'),
('fsi', 'Social', 'SIZA Social',                        'siza-social',         'recognized'),
('fsi', 'Social', 'SA8000',                             NULL,                  'recognized');

-- ── Équivalence : pour un référentiel donné, les autres référentiels EN BASE
--    co-reconnus par le même schéma dans au moins un pilier commun. ───────────
create or replace function framework_equivalences(focal text)
returns table (slug text, title text, shared_pillars text[])
language sql stable as $$
    with focal_pillars as (
        select distinct scheme_slug, pillar from recognition where framework_slug = focal
    )
    select f.slug, f.title, array_agg(distinct r.pillar order by r.pillar)
    from recognition r
    join framework f on f.slug = r.framework_slug
    join focal_pillars fp on fp.scheme_slug = r.scheme_slug and fp.pillar = r.pillar
    where r.framework_slug is not null and r.framework_slug <> focal
    group by f.slug, f.title
    order by cardinality(array_agg(distinct r.pillar)) desc, f.title;
$$;
