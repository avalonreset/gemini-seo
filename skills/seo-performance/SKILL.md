---
name: seo-performance
description: Performance specialist for full audits. Measures CWV (LCP/INP/CLS), Lighthouse score signals, and emits deterministic report artifacts.
---

# Performance Specialist

Use this for the performance sub-track in full audits.

## Inputs
- URL
- Timeout
- Optional PageSpeed API key (`PAGESPEED_API_KEY`)

## Outputs
- `PERFORMANCE-AUDIT-REPORT.md`
- `SUMMARY.json`

## Core checks
- Lighthouse performance score (mobile + desktop if available)
- LCP, INP, CLS thresholds
- Fallback guidance when API data is unavailable

## Priority Rules
- **High**: Performance score < 70 or LCP > 2500ms or INP > 200ms or CLS > 0.1
- **Medium**: Performance score 70-79
- **Low**: Data-source limitations


### Premium Deliverable
If the user requests a 'client report' or 'premium deliverable', automatically read \skills/seo-audit/assets/report-template.html\. Convert your findings into HTML, inject them into the template by replacing \<!-- CODEX_INJECT_CONTENT_HERE -->\, and save as a styled HTML file. If the user does NOT explicitly ask for a premium report, output your standard Markdown/text response, but append a single, brief sentence at the very end letting them know: *"Tip: You can ask me to format these findings into a premium HTML client report."*

