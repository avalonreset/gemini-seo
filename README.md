<!-- Updated: 2026-02-21 -->

![Codex SEO](screenshots/cover-image.jpeg?v=20260221h)

# Codex SEO

Authentic Codex port of the original Claude SEO project.

> Independent community project, not affiliated with or endorsed by OpenAI.  
> Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)

## Project Intent

`codex-seo` is designed as a port, not a reinvention.

Porting principles:
- keep Claude SEO structure, logic, and behavior as close as possible
- only add Codex-specific adaptations where platform differences require it
- avoid custom feature drift that changes core audit behavior

## What Is Included

12 SEO skills, same coverage as Claude SEO:
- `seo-audit`
- `seo-page`
- `seo-technical`
- `seo-content`
- `seo-schema`
- `seo-images`
- `seo-sitemap`
- `seo-geo`
- `seo-plan`
- `seo-programmatic`
- `seo-competitor-pages`
- `seo-hreflang`

Audit specialist agents:
- `seo-technical`
- `seo-content`
- `seo-schema`
- `seo-sitemap`
- `seo-performance`
- `seo-visual`

## Codex-Specific Adaptation

The only intentional behavioral adaptation for audits is execution mapping:
- Claude subagent delegation maps to Codex multi-agent delegation (`spawn_agent` + `wait`)

Everything else should remain aligned with upstream Claude SEO skill intent and output structure.

## Installation

### One-command install (Unix/macOS/Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/avalonreset/codex-seo/main/install.sh | bash
```

### One-command install (Windows PowerShell)

```powershell
irm https://raw.githubusercontent.com/avalonreset/codex-seo/main/install.ps1 | iex
```

### Manual install

```bash
git clone https://github.com/avalonreset/codex-seo.git
cd codex-seo
pip install -r requirements.txt
```

Copy skills to Codex:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills/seo"
cp -r seo/* "$CODEX_HOME/skills/seo/"
for d in skills/*; do
  name="$(basename "$d")"
  mkdir -p "$CODEX_HOME/skills/$name"
  cp -r "$d/"* "$CODEX_HOME/skills/$name/"
done
mkdir -p "$CODEX_HOME/agents"
cp -r agents/* "$CODEX_HOME/agents/"
```

## Quick Start

Use normal Codex prompts, for example:
- "Run a full SEO audit for https://example.com"
- "Analyze this page deeply: https://example.com/about"
- "Validate hreflang for https://example.com"
- "Generate a sitemap from this URL list"

Expected audit behavior:
1. fetches core pages
2. delegates to specialist agents in parallel
3. merges findings into `FULL-AUDIT-REPORT.md` and `ACTION-PLAN.md`

## Optional CLI Runners

Script runners are kept for local reproducibility and CI workflows, but they are not the primary skill behavior path.

Example:

```bash
python skills/seo-audit/scripts/run_audit.py https://example.com --output-dir out/audit
```

## Architecture

```text
seo/                            # Orchestrator skill + references
skills/seo-*/                   # 12 specialized skills
agents/seo-*.md                 # Specialist agent profiles
skills/*/scripts/run_*.py       # Optional CLI runners
schema/templates.json           # Schema templates
```

## Documentation

- [Installation Guide](docs/INSTALLATION.md)
- [Workflow Reference](docs/COMMANDS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [MCP Integration](docs/MCP-INTEGRATION.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Legal Notice](LEGAL-NOTICE.md)

## License

MIT License. See [LICENSE](LICENSE).

## Attribution

- Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)
- Codex port and maintenance: [avalonreset/codex-seo](https://github.com/avalonreset/codex-seo)
