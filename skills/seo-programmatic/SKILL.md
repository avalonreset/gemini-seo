---
name: seo-programmatic
description: >
  Programmatic SEO planning and analysis for pages generated at scale from data
  sources. Deterministically audits data quality, URL structures, thin-content
  risk, and index bloat; and generates implementation blueprints for scaled page
  systems. Use for prompts like "programmatic SEO", "pages at scale",
  "dynamic pages", "template pages", or "data-driven SEO".
---

# Programmatic SEO Analysis & Planning

Use deterministic execution for reproducible audits and plans.

## Runtime

- Main runner: `skills/seo-programmatic/scripts/run_programmatic.py`
- Dependencies: standard library only (see `skills/seo-programmatic/requirements.txt`)

## Quick Run

Analyze a dataset + existing page inventory:

```bash
python skills/seo-programmatic/scripts/run_programmatic.py analyze \
  --dataset-file records.csv \
  --pages-file pages.csv \
  --output-dir seo-programmatic-output
```

Generate a rollout blueprint:

```bash
python skills/seo-programmatic/scripts/run_programmatic.py plan \
  --project-name "Acme Integrations" \
  --pattern integration \
  --entity-singular integration \
  --entity-plural integrations \
  --base-path /integrations \
  --expected-pages 1200 \
  --output-dir seo-programmatic-output
```

## Analyze Inputs

- `dataset-file` (required): CSV or JSON records used to generate pages
- `pages-file` (optional): CSV or JSON page inventory with quality metrics
- `sample-size` (default `300`): max rows to evaluate for near-duplicate checks
- `justified-scale` (optional): mark high-volume rollout as already approved
- `output-dir`

### Expected `pages-file` fields (flexible naming)

- URL: `url` or `page_url`
- Word count: `word_count` or `words`
- Unique content %: `unique_content_pct` or `uniqueness_pct`
- Reviewed flag: `reviewed` or `content_reviewed`
- Canonical: `canonical_url` or `canonical`
- Indexability: `indexable` / `noindex`
- Internal links: `internal_links`
- Status code: `status_code`

## Plan Inputs

- `project-name` (required)
- `pattern`: `tool|location-service|integration|glossary|template|custom`
- `entity-singular`, `entity-plural`
- `base-path` (default `/pages`)
- `expected-pages` (default `250`)
- `batch-size` (default `100`)
- `minimum-unique-pct` (default `40`)
- `minimum-word-count` (default `300`)
- `output-dir`

## Checks

1. Data quality: row volume, missing-field rates, duplicate/near-duplicate signals.
2. URL hygiene: lowercase/hyphen rules, duplicates, query-parameter misuse, length limits.
3. Thin-content risk: low uniqueness and low word-count flags.
4. Review gate enforcement:
   - `100+` pages without sufficient review sample -> warning
   - `500+` pages without approval (`--justified-scale`) -> hard stop
5. Canonical/indexability checks: canonical mismatches and low-value indexable pages.
6. Internal-linking density distribution across programmatic pages.
7. Category scoring and prioritized remediation actions.

## Guardrails

1. Treat outputs as operational audit/planning guidance, not ranking guarantees.
2. Keep low-value pages noindexed until quality gates pass.
3. Prevent blind scale expansion without staged rollout and QA sampling.
4. Preserve deterministic outputs from identical inputs.

## Output Contract

### Analyze Mode

- `PROGRAMMATIC-SEO-REPORT.md`
- `QUALITY-GATES.json`
- `SUMMARY.json`

### Plan Mode

- `PROGRAMMATIC-BLUEPRINT.md`
- `URL-PATTERN-EXAMPLES.csv`
- `QUALITY-GATES.json`
- `SUMMARY.json`
