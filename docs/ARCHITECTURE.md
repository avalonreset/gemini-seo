# Architecture

## Overview

Codex SEO uses a modular skill architecture:

- `seo/` is the orchestrator skill (routing + shared references)
- `skills/seo-*` contains task skills plus audit specialist runners (including `seo-performance` and `seo-visual`)
- each skill has a deterministic Python runner in `skills/*/scripts/`
- optional specialist agent profiles live in `agents/`

## Repository Layout

```text
codex-seo/
├── seo/
│   ├── SKILL.md
│   └── references/
│       ├── cwv-thresholds.md
│       ├── schema-types.md
│       ├── eeat-framework.md
│       └── quality-gates.md
├── skills/
│   ├── seo-audit/
│   │   ├── SKILL.md
│   │   └── scripts/run_audit.py
│   ├── seo-page/
│   ├── seo-technical/
│   ├── seo-content/
│   ├── seo-schema/
│   ├── seo-images/
│   ├── seo-sitemap/
│   ├── seo-geo/
│   ├── seo-performance/
│   ├── seo-visual/
│   ├── seo-plan/
│   ├── seo-programmatic/
│   ├── seo-competitor-pages/
│   └── seo-hreflang/
├── agents/
├── schema/
└── docs/
```

## Component Types

### Skills

Each skill is a `SKILL.md` instruction package with:

- activation description
- workflow steps
- guardrails
- deterministic runner reference

### Deterministic Runners

Each skill has a runner script to support reproducible, non-chat execution:

- same input schema every run
- stable output artifact set
- easier CI integration and auditing

### Agent Profiles

Files in `agents/` are specialist prompts for decomposition patterns. They are optional and can be used as reference guidance when spawning focused multi-agents.

### Reference Files

Reference docs under `seo/references/` and `skills/*/assets/` provide static SEO frameworks and templates loaded only when needed.

## Execution Model

### Skill-Driven Mode (Codex)

1. User asks for an SEO task in natural language.
2. Codex selects the relevant skill by intent.
3. Skill workflow executes with guardrails.
4. For `/seo audit`, Codex should prefer parallel `spawn_agent` specialist execution.
5. Multi-agent prerequisite in Codex chat: run `/experimental` and enable **Multi-agent**.
6. Runner scripts are used when deterministic local/CI output is explicitly requested.

### Runner Mode (Direct CLI)

1. Call `python skills/<skill>/scripts/run_*.py ...`.
2. Script validates input and safety constraints.
3. Script emits report artifacts into `--output-dir`.

## Design Principles

1. Progressive disclosure:
   - concise top-level orchestration
   - deep guidance in specialized skills
2. Deterministic first:
   - scripts produce stable outputs for QA/review
3. Safety guardrails:
   - URL normalization, scope checks, and public-target validation
4. Domain quality controls:
   - CWV thresholds, schema deprecations, location-page gates, E-E-A-T checks

## Naming Conventions

| Type | Pattern | Example |
|---|---|---|
| Skill | `skills/seo-{name}/SKILL.md` | `skills/seo-audit/SKILL.md` |
| Runner | `skills/seo-{name}/scripts/run_*.py` | `skills/seo-audit/scripts/run_audit.py` |
| Agent profile | `agents/seo-{name}.md` | `agents/seo-technical.md` |
| Reference | `seo/references/{topic}.md` | `seo/references/cwv-thresholds.md` |
| Template | `skills/seo-plan/assets/{industry}.md` | `skills/seo-plan/assets/saas.md` |

## Extending the System

### Add a New Skill

1. Create `skills/seo-new/SKILL.md`
2. Add `skills/seo-new/scripts/run_new.py`
3. Add `skills/seo-new/requirements.txt` (if needed)
4. Update `seo/SKILL.md` routing references
5. Add documentation entry in `docs/COMMANDS.md`

### Add New Reference Data

1. Add file under `seo/references/` or `skills/<skill>/assets/`
2. Reference it from the relevant `SKILL.md`
3. Keep files focused and load-on-demand
