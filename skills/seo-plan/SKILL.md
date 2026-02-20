---
name: seo-plan
description: >
  Strategic SEO planning for new or existing websites with deterministic output.
  Generates industry-specific strategy docs, competitive gap analysis, content
  calendar, implementation roadmap, and site architecture plans. Use for prompts
  like "SEO strategy", "SEO roadmap", "content plan", or "site architecture".
---

# Strategic SEO Planning

Use deterministic execution to produce reproducible planning artifacts.

## Runtime

- Main runner: `skills/seo-plan/scripts/run_plan.py`
- Dependencies: standard library only (see `skills/seo-plan/requirements.txt`)
- Industry templates: `skills/seo-plan/assets/*.md`

## Quick Run

Basic SaaS plan:

```bash
python skills/seo-plan/scripts/run_plan.py \
  --industry saas \
  --business-name "Acme CRM" \
  --website https://example.com \
  --goals "increase non-brand demos, improve comparison-page rankings" \
  --competitors "HubSpot,Salesforce,Pipedrive" \
  --content-pillars "crm automation,sales forecasting,pipeline management" \
  --output-dir seo-plan-output
```

Run from brief JSON:

```bash
python skills/seo-plan/scripts/run_plan.py \
  --brief-file seo-brief.json \
  --output-dir seo-plan-output
```

## Inputs

- `--industry`: `saas|local-service|ecommerce|publisher|agency|generic`
- `--brief-file` (optional): JSON brief with planning inputs
- `--baseline-kpis-file` (optional): JSON object for KPI baselines
- `--business-name`, `--website`, `--audience`, `--budget`
- `--goals`, `--competitors`, `--content-pillars`, `--markets` (comma-separated)
- `--timeline-months` (default `12`)
- `--cadence` (`weekly|biweekly|monthly`, default `weekly`)
- `--start-date` (`YYYY-MM-DD`, defaults to current UTC date)
- `--output-dir`

## Checks

1. Select and load the correct industry template from `assets/`.
2. Validate URL format and normalize list-based inputs.
3. Build KPI targets using provided baselines when available.
4. Generate competitor opportunity matrix and gap themes.
5. Generate a cadence-based content calendar.
6. Produce a 4-phase implementation roadmap with risks and dependencies.
7. Produce site architecture and internal-linking guidance from template structure.

## Guardrails

1. Do not fabricate verified competitor claims; mark findings as planning assumptions.
2. Keep generated plans tied to user-provided goals, timeline, and market scope.
3. Cap unrealistic timelines by warning when `timeline-months < 6`.
4. Preserve deterministic behavior from identical inputs.

## Output Contract

- `SEO-STRATEGY.md`
- `COMPETITOR-ANALYSIS.md`
- `CONTENT-CALENDAR.md`
- `IMPLEMENTATION-ROADMAP.md`
- `SITE-STRUCTURE.md`
- `SUMMARY.json`
