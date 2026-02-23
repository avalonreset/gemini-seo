---
name: gemini-seo
description: Comprehensive SEO analysis for any website or business type. Use for full site audits, single-page deep analysis, technical SEO checks, schema markup detection/generation, content quality assessment (E-E-A-T), image optimization, sitemaps, AI Overviews (GEO), programmatic SEO, and competitor analysis.
---

# Gemini SEO

Gemini SEO is a comprehensive suite of professional-grade SEO analysis tools designed specifically for the Gemini CLI.

When the user requests an SEO task, first determine the scope of their request and load the appropriate reference file for detailed instructions. Do NOT attempt to execute the task before reading the relevant reference file.

## Workflows and Capabilities

### 1. Full Site Audit
For comprehensive, site-wide SEO health checks.
**Read first:** `references/seo-audit.md`

### 2. Deep Single-Page Analysis
For analyzing on-page SEO, content quality, and technical tags of a single URL.
**Read first:** `references/seo-page.md`

### 3. Technical SEO Review
For analyzing crawlability, indexability, security, URL structure, and Core Web Vitals.
**Read first:** `references/seo-technical.md`

### 4. Content Quality & E-E-A-T
For evaluating E-E-A-T signals, readability, content depth, and AI citation readiness.
**Read first:** `references/seo-content.md`

### 5. Schema Markup
For detecting, validating, or generating Schema.org structured data (JSON-LD).
**Read first:** `references/seo-schema.md`

### 6. Sitemap Architecture
For validating XML sitemaps or generating new ones with industry templates.
**Read first:** `references/seo-sitemap.md`

### 7. Core Web Vitals & Performance
For measuring LCP, INP, and CLS.
**Read first:** `references/seo-performance.md`

### 8. Image Optimization
For auditing alt text, formats, file sizes, responsive attributes, and lazy loading.
**Read first:** `references/seo-images.md`

### 9. AI Search Readiness (GEO)
For Generative Engine Optimization (AI Overviews, ChatGPT, Perplexity).
**Read first:** `references/seo-geo.md`

### 10. Competitor Comparison Pages
For building "vs", alternatives, and roundup pages.
**Read first:** `references/seo-competitor-pages.md`

### 11. Hreflang & International SEO
For validating hreflang graph integrity or generating implementations.
**Read first:** `references/seo-hreflang.md`

### 12. Programmatic SEO
For auditing scaled-page systems for thin-content risk and index bloat.
**Read first:** `references/seo-programmatic.md`

### 13. Strategic Planning
For producing phased SEO roadmaps, KPI targets, and content calendars.
**Read first:** `references/seo-plan.md`

### 14. Visual Analysis
For capturing screenshots, testing mobile rendering, and analyzing above-the-fold content.
**Read first:** `references/seo-visual.md`

## Utilities & Assets

- **Browser Automation:** Use `scripts/capture_screenshot.py` to capture screenshots.
- **Page Fetching:** Use `scripts/fetch_page.py` or `scripts/parse_html.py` for HTML retrieval and parsing if WebFetch fails or needs bypass.
- **Premium Reports:** Use `assets/report-template.html` when compiling premium client deliverables.
- **Schema Templates:** Use `assets/templates.json` for schema generation reference.
- **Industry Plans:** Use `assets/plan-templates/` for strategic planning templates.

## Global Quality Gates & References
You may also need to consult these files depending on the task:
- `references/cwv-thresholds.md` — Core Web Vitals thresholds
- `references/eeat-framework.md` — E-E-A-T evaluation criteria
- `references/quality-gates.md` — Content length and location page limits
- `references/schema-types.md` — Supported schema types