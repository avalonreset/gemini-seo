---
name: seo
description: >
  Comprehensive SEO analysis orchestration for any website or business type.
  Routes requests to specialized SEO skills for full audits, page analysis,
  technical checks, content quality (E-E-A-T), schema, images, sitemap,
  GEO/AI-search readiness, programmatic SEO, competitor pages, hreflang,
  and strategic planning.
---

# SEO Orchestrator Skill

Use this orchestrator when the user asks for broad SEO analysis or is unsure which specialized workflow to run.

## Routing Map

Map user intent to the appropriate skill:

- Full site baseline audit -> `seo-audit`
- Single URL deep dive -> `seo-page`
- Crawl/index/render/security issues -> `seo-technical`
- E-E-A-T / editorial quality -> `seo-content`
- Structured data detection or generation -> `seo-schema`
- Image optimization and media delivery -> `seo-images`
- Sitemap validation or sitemap generation -> `seo-sitemap`
- AI search and citation readiness (GEO) -> `seo-geo`
- Strategic roadmap and implementation plan -> `seo-plan`
- Programmatic SEO at scale -> `seo-programmatic`
- Competitor comparison page workflows -> `seo-competitor-pages`
- International hreflang validation/generation -> `seo-hreflang`

## Orchestration Policy

When a request spans multiple areas:

1. Start with `seo-audit` for baseline if no prior evidence exists.
2. Decompose into specialist tracks as needed (technical, content, schema, sitemap, performance, visual).
3. Merge findings into one prioritized remediation sequence.
4. Keep severity ordering strict: Critical -> High -> Medium -> Low.

## Industry Detection Heuristics

Detect likely business model from homepage signals:

- SaaS: `/pricing`, `/features`, `/integrations`, docs, trial/signup CTAs
- Local service: service-area language, address/phone prominence, map embeds
- E-commerce: product/category/cart flows, product schema
- Publisher: article index patterns, author/timestamp signals
- Agency: case-study/portfolio/service-led structure

Use detected type to bias recommendations, templates, and guardrails.

## Quality Gates

Apply hard rules:

- Warning at 30+ location pages without strong uniqueness
- Hard stop at 50+ location pages unless explicitly justified
- Never recommend deprecated HowTo schema
- FAQ schema only when site context qualifies
- Use INP (not FID) in Core Web Vitals guidance

## Reference Files

Load only what is needed:

- `references/cwv-thresholds.md`
- `references/schema-types.md`
- `references/eeat-framework.md`
- `references/quality-gates.md`

## Scoring Weights

| Category | Weight |
|---|---|
| Technical SEO | 25% |
| Content Quality | 25% |
| On-Page SEO | 20% |
| Schema / Structured Data | 10% |
| Performance (CWV) | 10% |
| Images | 5% |
| AI Search Readiness | 5% |

## Output Requirements

For consolidated audits, return:

- executive summary with top risks
- score breakdown with evidence
- issue list grouped by severity
- staged action plan (immediate, 1-2 weeks, 30-day backlog)
