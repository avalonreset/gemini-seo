
# Full Website SEO Audit

## Process

1. **Fetch homepage** — use `scripts/fetch_page.py` to retrieve HTML
2. **Detect business type** — analyze homepage signals per seo orchestrator
3. **Crawl site** — follow internal links up to 500 pages, respect robots.txt
4. **Execute Specialist Checks** (load the relevant reference files as needed):
   - `references/seo-technical.md` — robots.txt, sitemaps, canonicals, Core Web Vitals, security headers
   - `references/seo-content.md` — E-E-A-T, readability, thin content, AI citation readiness
   - `references/seo-schema.md` — detection, validation, generation recommendations
   - `references/seo-sitemap.md` — structure analysis, quality gates, missing pages
   - `references/seo-performance.md` — LCP, INP, CLS measurements
   - `references/seo-visual.md` — screenshots, mobile testing, above-fold analysis
5. **Score** — aggregate into SEO Health Score (0-100)
6. **Report** — generate prioritized action plan
7. **Deliverables** — automatically read `assets/report-template.html`. Convert your `FULL-AUDIT-REPORT.md` into HTML, and inject it into the template by replacing `<!-- GEMINI_INJECT_CONTENT_HERE -->`. Save this as `CLIENT-SEO-AUDIT.html`. Also generate a PDF version named `CLIENT-SEO-AUDIT.pdf` (using browser automation or system tools if available, or instruct the user to "Print to PDF" from the generated HTML).

## Crawl Configuration

```
Max pages: 500
Respect robots.txt: Yes
Follow redirects: Yes (max 3 hops)
Timeout per page: 30 seconds
Concurrent requests: 5
Delay between requests: 1 second
```

## Output Files

- `FULL-AUDIT-REPORT.md` — Comprehensive findings
- `ACTION-PLAN.md` — Prioritized recommendations (Critical → High → Medium → Low)
- `CLIENT-SEO-AUDIT.html` — Premium styled client deliverable
- `CLIENT-SEO-AUDIT.pdf` — PDF version of the client deliverable
- `screenshots/` — Desktop + mobile captures (if Playwright available)

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

## Report Structure

### Executive Summary
- Overall SEO Health Score (0-100)
- Business type detected
- Top 5 critical issues
- Top 5 quick wins

### Technical SEO
- Crawlability issues
- Indexability problems
- Security concerns
- Core Web Vitals status

### Content Quality
- E-E-A-T assessment
- Thin content pages
- Duplicate content issues
- Readability scores

### On-Page SEO
- Title tag issues
- Meta description problems
- Heading structure
- Internal linking gaps

### Schema & Structured Data
- Current implementation
- Validation errors
- Missing opportunities

### Performance
- LCP, INP, CLS scores
- Resource optimization needs
- Third-party script impact

### Images
- Missing alt text
- Oversized images
- Format recommendations

### AI Search Readiness
- Citability score
- Structural improvements
- Authority signals

## Priority Definitions

- **Critical**: Blocks indexing or causes penalties (fix immediately)
- **High**: Significantly impacts rankings (fix within 1 week)
- **Medium**: Optimization opportunity (fix within 1 month)
- **Low**: Nice to have (backlog)




