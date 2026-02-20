---
name: seo-sitemap
description: >
  Analyze existing XML sitemaps or generate new sitemap files from URL lists
  with protocol checks, status sampling, and location-page quality gates.
  Use for prompts like "sitemap audit", "sitemap issues", "generate sitemap",
  or "validate XML sitemap".
---

# Sitemap Analysis and Generation

Use deterministic execution for reproducible sitemap validation and output files.

## Runtime

- Main runner: `skills/seo-sitemap/scripts/run_sitemap.py`
- Dependencies: `skills/seo-sitemap/requirements.txt`

## Quick Run

Analyze:

```bash
python skills/seo-sitemap/scripts/run_sitemap.py analyze \
  --sitemap-url https://example.com/sitemap.xml \
  --output-dir seo-sitemap-output
```

Generate:

```bash
python skills/seo-sitemap/scripts/run_sitemap.py generate \
  --base-url https://example.com \
  --urls-file urls.txt \
  --output-dir seo-sitemap-output
```

## Analyze Mode

### Inputs

- `--sitemap-url` or `--sitemap-file` (one required)
- `--crawl-urls-file` (optional): newline list for coverage diff
- `--status-sample-limit` (default `200`)
- `--noindex-scan-limit` (default `50`)
- `--include-meta-noindex` (optional): parse HTML snippets for meta noindex

### Checks

1. XML validity and root type (`urlset`/`sitemapindex`)
2. URL file size limit (`<= 50,000` per sitemap file)
3. Non-200 and redirected URL sampling
4. Noindex signal sampling (`X-Robots-Tag`, optional meta robots)
5. HTTPS-only URL enforcement
6. Deprecated tag detection (`priority`, `changefreq`)
7. Identical `<lastmod>` pattern detection
8. robots.txt sitemap reference check (URL mode)
9. Optional crawl-vs-sitemap coverage diff

### Output

- `VALIDATION-REPORT.md`
- `SUMMARY.json`

## Generate Mode

### Inputs

- `--base-url` (required)
- `--urls-file` (required): newline-delimited URLs
- `--split-size` (default `50000`, max `50000`)
- `--default-lastmod` (optional `YYYY-MM-DD`)
- `--allow-location-scale` (optional hard-stop override)

### Quality Gates

1. At `30+` location-like URLs: emit warning (require meaningful uniqueness).
2. At `50+` location-like URLs: hard stop unless `--allow-location-scale` is set.
3. Skip out-of-scope URLs (host mismatch against base URL).

### Output

- `sitemap.xml` (single file) or split `sitemap-*.xml` plus `sitemap_index.xml`
- `STRUCTURE.md`
- `SUMMARY.json`

## Guardrails

1. Only `http`/`https` URLs are accepted.
2. Reject localhost/private/reserved/loopback targets.
3. Do not treat sampled URL checks as full-site crawl guarantees.
4. Do not output deprecated sitemap tags by default.

