# Workflow Reference

## Overview

Codex SEO supports two execution modes:

1. Skill-driven mode in Codex (natural-language request, Codex routes to the right skill)
2. Deterministic runner mode (direct Python command for repeatable local/CI output)

## Skill Routing Examples

Use prompts like:

- "Run a full SEO audit for https://example.com"
- "Analyze this page for SEO depth: https://example.com/about"
- "Validate hreflang for this site and produce fixes"
- "Generate a sitemap from this URL list"
- "Create a strategic SEO plan for a SaaS business"

## Deterministic Runners

### Full Site Audit

```bash
python skills/seo-audit/scripts/run_audit.py https://example.com --output-dir out/audit
```

### Single Page Audit

```bash
python skills/seo-page/scripts/run_page_audit.py https://example.com/about --output-dir out/page
```

### Technical SEO Audit

```bash
python skills/seo-technical/scripts/run_technical_audit.py https://example.com --output-dir out/technical
```

### Content / E-E-A-T Audit

```bash
python skills/seo-content/scripts/run_content_audit.py https://example.com/blog/post --output-dir out/content
```

### Schema Analysis / Generation

```bash
python skills/seo-schema/scripts/run_schema.py analyze --url https://example.com --output-dir out/schema-analyze
python skills/seo-schema/scripts/run_schema.py generate --template article --page-url https://example.com/post --output-dir out/schema-generate
```

### GEO Analysis

```bash
python skills/seo-geo/scripts/run_geo_analysis.py --url https://example.com/post --output-dir out/geo
```

### Image SEO Audit

```bash
python skills/seo-images/scripts/run_image_audit.py --url https://example.com --output-dir out/images
```

### Sitemap Analyze / Generate

```bash
python skills/seo-sitemap/scripts/run_sitemap.py analyze --sitemap-url https://example.com/sitemap.xml --output-dir out/sitemap-analyze
python skills/seo-sitemap/scripts/run_sitemap.py generate --base-url https://example.com --urls-file urls.txt --output-dir out/sitemap-generate
```

### Hreflang Validate / Generate

```bash
python skills/seo-hreflang/scripts/run_hreflang.py validate --url https://example.com --output-dir out/hreflang-validate
python skills/seo-hreflang/scripts/run_hreflang.py generate --mapping-file mapping.json --output-dir out/hreflang-generate
```

### Programmatic SEO Analyze / Plan

```bash
python skills/seo-programmatic/scripts/run_programmatic.py analyze --dataset-file dataset.csv --output-dir out/programmatic-analyze
python skills/seo-programmatic/scripts/run_programmatic.py plan --project-name "Acme" --pattern location-service --entity-singular location --entity-plural locations --base-path /services --expected-pages 200 --output-dir out/programmatic-plan
```

### Competitor Comparison Pages

```bash
python skills/seo-competitor-pages/scripts/run_competitor_pages.py --mode vs --your-product "Acme" --competitors "Competitor" --output-dir out/competitor
```

### Strategic SEO Plan

```bash
python skills/seo-plan/scripts/run_plan.py --industry saas --business-name "Acme" --website https://example.com --output-dir out/plan
```

## Skill-to-Runner Map

| Skill | Runner |
|---|---|
| `seo-audit` | `skills/seo-audit/scripts/run_audit.py` |
| `seo-page` | `skills/seo-page/scripts/run_page_audit.py` |
| `seo-technical` | `skills/seo-technical/scripts/run_technical_audit.py` |
| `seo-content` | `skills/seo-content/scripts/run_content_audit.py` |
| `seo-schema` | `skills/seo-schema/scripts/run_schema.py` |
| `seo-geo` | `skills/seo-geo/scripts/run_geo_analysis.py` |
| `seo-images` | `skills/seo-images/scripts/run_image_audit.py` |
| `seo-sitemap` | `skills/seo-sitemap/scripts/run_sitemap.py` |
| `seo-hreflang` | `skills/seo-hreflang/scripts/run_hreflang.py` |
| `seo-programmatic` | `skills/seo-programmatic/scripts/run_programmatic.py` |
| `seo-competitor-pages` | `skills/seo-competitor-pages/scripts/run_competitor_pages.py` |
| `seo-plan` | `skills/seo-plan/scripts/run_plan.py` |
