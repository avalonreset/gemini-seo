<!-- Updated: 2026-02-20 -->

![Codex SEO](screenshots/cover-image.jpeg)

# Codex SEO

Codex-native SEO skill suite for technical, on-page, content, schema, image, sitemap, GEO, hreflang, programmatic, competitor-page, and strategic SEO workflows.

This repository ports the original Claude SEO project into a Codex skill layout while preserving deterministic Python runners for repeatable output artifacts.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What You Get

- 12 specialized SEO skills under `skills/seo-*`
- 1 orchestrator skill under `seo/SKILL.md`
- Deterministic runners for each skill (`skills/*/scripts/run_*.py`)
- Optional specialist agent profiles in `agents/`
- SEO references, schema templates, and planning assets

## Quick Start (Codex)

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy skills to your Codex skills directory:

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

PowerShell equivalent:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$env:USERPROFILE\\.codex" }
New-Item -ItemType Directory -Force -Path "$codexHome\\skills\\seo" | Out-Null
Copy-Item -Recurse -Force "seo\\*" "$codexHome\\skills\\seo\\"
Get-ChildItem -Directory skills | ForEach-Object {
  $target = "$codexHome\\skills\\$($_.Name)"
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  Copy-Item -Recurse -Force "$($_.FullName)\\*" $target
}
```

3. Start Codex and ask for a workflow by intent, for example:

- "Run a full SEO audit for https://example.com"
- "Analyze hreflang for https://example.com and return fixes"
- "Generate a sitemap from this URL list"

## Deterministic Runner Commands

Use these for reproducible CI/local runs:

| Workflow | Runner |
|---|---|
| Full audit | `python skills/seo-audit/scripts/run_audit.py https://example.com --output-dir out/audit` |
| Single page | `python skills/seo-page/scripts/run_page_audit.py https://example.com/about --output-dir out/page` |
| Technical | `python skills/seo-technical/scripts/run_technical_audit.py https://example.com --output-dir out/technical` |
| Content | `python skills/seo-content/scripts/run_content_audit.py https://example.com/post --output-dir out/content` |
| Schema analyze | `python skills/seo-schema/scripts/run_schema.py analyze --url https://example.com --output-dir out/schema` |
| Sitemap analyze | `python skills/seo-sitemap/scripts/run_sitemap.py analyze --sitemap-url https://example.com/sitemap.xml --output-dir out/sitemap` |
| GEO | `python skills/seo-geo/scripts/run_geo_analysis.py --url https://example.com --output-dir out/geo` |
| Images | `python skills/seo-images/scripts/run_image_audit.py --url https://example.com --output-dir out/images` |
| Hreflang validate | `python skills/seo-hreflang/scripts/run_hreflang.py validate --url https://example.com --output-dir out/hreflang` |
| Programmatic analyze | `python skills/seo-programmatic/scripts/run_programmatic.py analyze --dataset-file data.csv --output-dir out/programmatic` |
| Competitor page | `python skills/seo-competitor-pages/scripts/run_competitor_pages.py --mode vs --your-product \"Your Product\" --competitors \"Competitor\" --output-dir out/competitor` |
| Strategy plan | `python skills/seo-plan/scripts/run_plan.py --industry saas --business-name \"Acme\" --website https://example.com --output-dir out/plan` |

## Architecture

```text
seo/                            # Orchestrator SKILL.md + references
skills/seo-*/                   # 12 specialized skills
skills/*/scripts/run_*.py       # Deterministic runners
agents/seo-*.md                 # Optional specialist agent profiles
schema/templates.json           # Schema snippets
```

## MCP Integrations

Codex SEO can use MCP servers for live SEO data enrichment (Ahrefs, Semrush, GSC, PageSpeed, DataForSEO). See `docs/MCP-INTEGRATION.md`.

## Documentation

- [Installation Guide](docs/INSTALLATION.md)
- [Workflow Reference](docs/COMMANDS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MCP Integration](docs/MCP-INTEGRATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## License

MIT License. See `LICENSE`.

## Attribution

- Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)
- Codex port and adaptation: this repository
