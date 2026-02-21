<!-- Updated: 2026-02-20 -->

![Codex SEO](screenshots/cover-image.jpeg?v=20260221g)

# Codex SEO

Codex-first SEO skill suite with deterministic Python runners for repeatable audits, planning, and SEO artifact generation.

[![CI](https://github.com/avalonreset/codex-seo/actions/workflows/runners-ci.yml/badge.svg)](https://github.com/avalonreset/codex-seo/actions/workflows/runners-ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Why This Exists

`codex-seo` is a full port of `claude-seo` into a Codex-native workflow.

Goals of this port:
- keep the original vision and coverage
- remove Claude slash-command assumptions
- support Codex skill routing by intent
- preserve deterministic runner scripts for local/CI reliability

## What Changed vs Original Claude SEO

- Codex-native docs, install paths, and workflow guidance
- No `/seo ...` command dependency
- Runner-first command model (`skills/*/scripts/run_*.py`)
- Install/uninstall migrated from `~/.claude` to `$CODEX_HOME` (default `~/.codex`)
- CI added to validate runner syntax/compile/help behavior on push and PR
- Security hardening retained across runner fetch flows (SSRF-safe redirect handling)

## Skill Coverage (12)

- `seo-audit` - full-site bounded crawl + weighted scoring
- `seo-page` - deep single-page SEO analysis
- `seo-technical` - crawl/index/render/security diagnostics
- `seo-content` - E-E-A-T and content quality checks
- `seo-schema` - schema analyze + generate
- `seo-images` - image SEO + media optimization checks
- `seo-sitemap` - sitemap analyze + generate
- `seo-geo` - AI citation / GEO readiness
- `seo-plan` - strategic plan generation by business type
- `seo-programmatic` - programmatic SEO analyze + rollout planning
- `seo-competitor-pages` - comparison page generation workflows
- `seo-hreflang` - i18n hreflang validate + generate

## Installation

### One-command Install (Unix/macOS/Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/avalonreset/codex-seo/main/install.sh | bash
```

### One-command Install (Windows PowerShell)

```powershell
irm https://raw.githubusercontent.com/avalonreset/codex-seo/main/install.ps1 | iex
```

### Manual Install

```bash
git clone https://github.com/avalonreset/codex-seo.git
cd codex-seo
pip install -r requirements.txt
```

Then copy skills to Codex:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills/seo"
cp -r seo/* "$CODEX_HOME/skills/seo/"
for d in skills/*; do
  name="$(basename "$d")"
  mkdir -p "$CODEX_HOME/skills/$name"
  cp -r "$d/"* "$CODEX_HOME/skills/$name/"
done
```

## Quick Start (Codex Skill Mode)

Use intent-driven prompts, for example:

- "Run a full SEO audit for https://example.com"
- "Analyze this page deeply: https://example.com/about"
- "Validate hreflang for https://example.com and show fix list"
- "Generate a sitemap from this URL list"
- "Create a SaaS SEO plan for my site"

## Tool Cheat Sheet (Deterministic Runner Mode)

Use these commands for reproducible local/CI outputs.

| Workflow | Runner command |
|---|---|
| Full site audit | `python skills/seo-audit/scripts/run_audit.py https://example.com --output-dir out/audit` |
| Single page audit | `python skills/seo-page/scripts/run_page_audit.py https://example.com/about --output-dir out/page` |
| Technical SEO audit | `python skills/seo-technical/scripts/run_technical_audit.py https://example.com --output-dir out/technical` |
| Content / E-E-A-T audit | `python skills/seo-content/scripts/run_content_audit.py https://example.com/blog/post --output-dir out/content` |
| Schema analyze | `python skills/seo-schema/scripts/run_schema.py analyze --url https://example.com --output-dir out/schema-analyze` |
| Schema generate | `python skills/seo-schema/scripts/run_schema.py generate --template article --page-url https://example.com/post --output-dir out/schema-generate` |
| Sitemap analyze | `python skills/seo-sitemap/scripts/run_sitemap.py analyze --sitemap-url https://example.com/sitemap.xml --output-dir out/sitemap-analyze` |
| Sitemap generate | `python skills/seo-sitemap/scripts/run_sitemap.py generate --base-url https://example.com --urls-file urls.txt --output-dir out/sitemap-generate` |
| GEO analysis | `python skills/seo-geo/scripts/run_geo_analysis.py --url https://example.com --output-dir out/geo` |
| Image SEO audit | `python skills/seo-images/scripts/run_image_audit.py --url https://example.com --output-dir out/images` |
| Hreflang validate | `python skills/seo-hreflang/scripts/run_hreflang.py validate --url https://example.com --output-dir out/hreflang-validate` |
| Hreflang generate | `python skills/seo-hreflang/scripts/run_hreflang.py generate --mapping-file mapping.json --output-dir out/hreflang-generate` |
| Programmatic analyze | `python skills/seo-programmatic/scripts/run_programmatic.py analyze --dataset-file dataset.csv --output-dir out/programmatic-analyze` |
| Programmatic plan | `python skills/seo-programmatic/scripts/run_programmatic.py plan --project-name \"Acme\" --pattern location-service --entity-singular location --entity-plural locations --base-path /services --expected-pages 200 --output-dir out/programmatic-plan` |
| Competitor page generator | `python skills/seo-competitor-pages/scripts/run_competitor_pages.py --mode vs --your-product \"Acme\" --competitors \"Competitor\" --output-dir out/competitor` |
| Strategic SEO plan | `python skills/seo-plan/scripts/run_plan.py --industry saas --business-name \"Acme\" --website https://example.com --output-dir out/plan` |

## Output Artifacts

Runners write structured outputs into `--output-dir`, typically including:
- markdown reports (`*.md`)
- JSON summaries (`SUMMARY.json`)
- optional screenshots for visual-enabled flows

Examples:
- `FULL-AUDIT-REPORT.md`, `ACTION-PLAN.md` (`seo-audit`)
- `TECHNICAL-AUDIT-REPORT.md`, `TECHNICAL-ACTION-PLAN.md` (`seo-technical`)
- `PROGRAMMATIC-BLUEPRINT.md`, `QUALITY-GATES.json` (`seo-programmatic`)

## Visual Checks and Playwright

- Visual and mobile-browser checks use Playwright when available.
- If Playwright/Chromium is missing, visual sections skip gracefully or use non-visual fallback logic.
- For no-visual mode, use runner flags where available (`--visual off`, `--mobile-check off`).

## Architecture

```text
seo/                            # Orchestrator skill + references
skills/seo-*/                   # 12 specialized skills
skills/*/scripts/run_*.py       # Deterministic runners
agents/seo-*.md                 # Optional specialist agent profiles
schema/templates.json           # Schema templates
```

## Demo

This port does not yet include a dedicated Codex demo video.

Original upstream demo (Claude SEO):
- https://www.youtube.com/watch?v=COMnNlUakQk

Included here for project lineage and feature context.

## MCP Integrations

Codex SEO can be paired with MCP servers for live SEO data and enrichment:
- Ahrefs MCP
- Semrush MCP
- Google Search Console MCP
- PageSpeed Insights MCP
- DataForSEO MCP

See `docs/MCP-INTEGRATION.md` for setup examples.

## Documentation

- [Installation Guide](docs/INSTALLATION.md)
- [Workflow Reference](docs/COMMANDS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MCP Integration](docs/MCP-INTEGRATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## License

MIT License. See [LICENSE](LICENSE).

## Attribution

- Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)
- Codex adaptation, hardening, and packaging: [avalonreset/codex-seo](https://github.com/avalonreset/codex-seo)
