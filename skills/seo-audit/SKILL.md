---
name: seo-audit
description: >
  Run a full website SEO audit with a bounded crawl, parallel specialist tracks,
  weighted health scoring, and a prioritized remediation plan. Use for requests
  like "audit this site", "full SEO check", "website health report", or
  "comprehensive SEO baseline".
---

# Full Website SEO Audit

Execute an end-to-end audit for one domain. Keep the crawl safe, bounded, and reproducible.

## Runtime

- Main runner: `skills/seo-audit/scripts/run_audit.py`
- Install dependencies from `skills/seo-audit/requirements.txt`
- Optional visual checks require Playwright Chromium (`python -m playwright install chromium`)

## Quick Run

```bash
python skills/seo-audit/scripts/run_audit.py https://example.com --output-dir seo-audit-output --visual auto
```

## Inputs

- `target_url` (required): homepage or canonical domain URL
- `max_pages` (optional, default `500`, hard cap `500`)
- `include_visual_checks` (optional, default `true` when Playwright is available)

## Guardrails

1. Accept only `http` or `https` URLs.
2. Reject localhost, loopback, private, or reserved IP targets.
3. Respect `robots.txt`, canonical tags, and redirect limits.
4. Do not claim metrics that were not measured.

## Workflow

1. Normalize scope:
   - Resolve the canonical domain from `target_url`.
   - Keep only in-scope internal URLs.
2. Collect baseline page data:
   - Fetch pages with the built-in runner fetcher (30s timeout).
   - Parse pages with the built-in parser for tags, links, schema, media, and content signals.
3. Crawl:
   - Perform BFS crawl of internal links up to `max_pages`.
   - Use concurrency `5` and delay `1s` between requests per worker.
   - Stop early if crawl budget is exhausted or repeated failures occur.
4. Run specialist tracks in parallel when possible; otherwise run sequentially:
   - Technical SEO: robots, indexability, canonicals, redirects, headers, CWV readiness
   - Content Quality: E-E-A-T, thin/duplicate content, readability, citation readiness
   - On-Page SEO: titles, meta descriptions, heading structure, internal linking
   - Schema: detection, validation errors, missing opportunities
   - Performance: LCP/INP/CLS evidence and bottlenecks
   - Images: alt text, size/format/compression opportunities
   - AI Search Readiness: crawlability by AI bots, structured excerpt quality, brand mention signals
5. Score:
   - Calculate category scores (0-100) and weighted total.
   - If a category is not measurable, mark it `Not Measured` and renormalize the remaining weights.
6. Report:
   - Produce an executive summary, issue list by priority, and a staged fix plan.

## Crawl Defaults

```
Max pages: 500
Respect robots.txt: yes
Follow redirects: yes (max 3 hops)
Timeout per page: 30s
Concurrent requests: 5
Delay between requests: 1s
```

## Output Contract

- `FULL-AUDIT-REPORT.md`: complete findings with evidence and URLs
- `ACTION-PLAN.md`: prioritized remediation backlog (Critical > High > Medium > Low)
- `screenshots/`: desktop/mobile captures when visual tooling is available

## Scoring Weights

| Category | Weight |
|----------|--------|
| Technical SEO | 25% |
| Content Quality | 25% |
| On-Page SEO | 20% |
| Schema / Structured Data | 10% |
| Performance (CWV) | 10% |
| Images | 5% |
| AI Search Readiness | 5% |

## Priority Rules

- **Critical**: indexing blocked, major security/canonical failures, or penalty risk
- **High**: significant ranking impact
- **Medium**: clear optimization opportunity
- **Low**: backlog improvement
