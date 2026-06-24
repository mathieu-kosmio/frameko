-- Frameko — proto V1 — Voisinage & comparaison au niveau critère
-- Générique (indépendant du domaine) : tout repose sur le socle commun.
-- Deux fonctions :
--   1. framework_neighbors(focal)      → référentiels partageant des critères communs
--   2. framework_pair_detail(a, b)     → descente au critère : pour chaque critère
--                                        commun partagé, les exigences d'origine
--                                        des deux référentiels avec leur degré.

-- ── Voisinage : référentiels qui partagent des critères communs avec « focal » ─
create or replace function framework_neighbors(focal text)
returns table (
    slug      text,
    title     text,
    publisher text,
    n_shared  bigint,   -- critères communs partagés avec focal
    n_total   bigint     -- critères communs couverts par le voisin (taille)
)
language sql stable as $$
    with focal_cc as (
        select distinct common_criterion_id
        from framework_criterion where framework_slug = focal
    )
    select f.slug, f.title, f.publisher,
           count(distinct fc.common_criterion_id)
               filter (where fc.common_criterion_id in (select common_criterion_id from focal_cc)) as n_shared,
           count(distinct fc.common_criterion_id) as n_total
    from framework f
    join framework_criterion fc on fc.framework_slug = f.slug
    where f.slug <> focal
    group by f.slug, f.title, f.publisher
    order by n_shared desc, n_total desc;
$$;

-- ── Comparaison au niveau critère : exigences d'origine des deux côtés ─────────
-- Pour chaque critère commun partagé par A et B, agrège les exigences réelles de
-- chacun (référence, libellé, degré, niveau). Un côté peut compter plusieurs
-- exigences rattachées au même critère commun → jsonb_agg.
create or replace function framework_pair_detail(framework_a text, framework_b text)
returns table (
    common_code  text,
    common_label text,
    theme_slug   text,
    a_items      jsonb,
    b_items      jsonb
)
language sql stable as $$
    with shared as (
        select fc.common_criterion_id
        from framework_criterion fc
        where fc.framework_slug in (framework_a, framework_b)
        group by fc.common_criterion_id
        having count(distinct fc.framework_slug) = 2
    )
    select cc.code, cc.label_fr, cc.theme_slug,
        (select jsonb_agg(jsonb_build_object(
                    'reference', fa.reference, 'label', fa.label,
                    'degree', fa.degree, 'level', fa.level) order by fa.reference)
           from framework_criterion fa
           where fa.framework_slug = framework_a and fa.common_criterion_id = cc.id) as a_items,
        (select jsonb_agg(jsonb_build_object(
                    'reference', fb.reference, 'label', fb.label,
                    'degree', fb.degree, 'level', fb.level) order by fb.reference)
           from framework_criterion fb
           where fb.framework_slug = framework_b and fb.common_criterion_id = cc.id) as b_items
    from shared s
    join common_criterion cc on cc.id = s.common_criterion_id
    order by cc.code;
$$;
