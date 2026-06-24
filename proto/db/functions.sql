-- Frameko — proto V1 — Fonctions RPC
-- Recherche sémantique (pgvector cosinus <=>), couverture, auto-évaluation.

-- ── S2 : k critères communs les plus proches d'un vecteur de requête ─────────
create or replace function match_criteria(query_embedding vector(384), k int default 10)
returns table (
    code         text,
    label_fr     text,
    theme_slug   text,
    theme_label  text,
    similarity   float4
)
language sql stable as $$
    select cc.code, cc.label_fr, cc.theme_slug, t.label_fr,
           1 - (cc.embedding <=> query_embedding)
    from common_criterion cc
    left join theme t on t.slug = cc.theme_slug
    where cc.embedding is not null
    order by cc.embedding <=> query_embedding
    limit k;
$$;

-- ── S2 : k critères de référentiel les plus proches, avec degré ──────────────
create or replace function nearest_framework_criteria(query_embedding vector(384), k int default 10)
returns table (
    framework_slug  text,
    framework_title text,
    reference       text,
    label           text,
    level           text,
    degree          text,
    common_code     text,
    common_label    text,
    similarity      float4
)
language sql stable as $$
    select fc.framework_slug, f.title, fc.reference, fc.label, fc.level, fc.degree,
           cc.code, cc.label_fr, 1 - (fc.embedding <=> query_embedding)
    from framework_criterion fc
    join framework f on f.slug = fc.framework_slug
    join common_criterion cc on cc.id = fc.common_criterion_id
    where fc.embedding is not null
    order by fc.embedding <=> query_embedding
    limit k;
$$;

-- ── S2 : recouvrement entre deux référentiels par critère commun ─────────────
create or replace function framework_coverage(framework_a text, framework_b text)
returns table (
    common_code  text,
    common_label text,
    theme_slug   text,
    count_a      bigint,
    count_b      bigint
)
language sql stable as $$
    select cc.code, cc.label_fr, cc.theme_slug,
           count(*) filter (where fc.framework_slug = framework_a),
           count(*) filter (where fc.framework_slug = framework_b)
    from common_criterion cc
    join framework_criterion fc on fc.common_criterion_id = cc.id
    where fc.framework_slug in (framework_a, framework_b)
    group by cc.code, cc.label_fr, cc.theme_slug
    having count(*) filter (where fc.framework_slug = framework_a) > 0
        or count(*) filter (where fc.framework_slug = framework_b) > 0
    order by cc.code;
$$;

-- ── S3 : résultat d'auto-évaluation (taux de couverture + écarts) ────────────
create or replace function assessment_result(p_assessment_id uuid)
returns jsonb
language sql stable as $$
    with target as (
        select framework_slug from assessment where id = p_assessment_id
    ),
    covered as (
        select distinct fc.common_criterion_id
        from framework_criterion fc, target
        where fc.framework_slug = target.framework_slug
    ),
    answers as (
        select aa.common_criterion_id, aa.status
        from assessment_answer aa
        where aa.assessment_id = p_assessment_id
    ),
    joined as (
        select c.common_criterion_id, coalesce(a.status, 'non_repondu') as status
        from covered c
        left join answers a on a.common_criterion_id = c.common_criterion_id
    )
    select jsonb_build_object(
        'assessment_id',  p_assessment_id,
        'framework_slug', (select framework_slug from target),
        'total_common',   (select count(*) from covered),
        'conforme',       (select count(*) from joined where status = 'conforme'),
        'partiel',        (select count(*) from joined where status = 'partiel'),
        'non_conforme',   (select count(*) from joined where status = 'non_conforme'),
        'non_applicable', (select count(*) from joined where status = 'non_applicable'),
        'non_repondu',    (select count(*) from joined where status = 'non_repondu'),
        'coverage_rate',  round(
            (select count(*) from joined where status = 'conforme')::numeric
            / nullif((select count(*) from covered), 0), 4),
        'gaps', coalesce((
            select jsonb_agg(jsonb_build_object(
                       'code', cc.code, 'label', cc.label_fr, 'status', j.status)
                   order by cc.code)
            from joined j
            join common_criterion cc on cc.id = j.common_criterion_id
            where j.status <> 'conforme'
        ), '[]'::jsonb)
    );
$$;
