<!-- Updated: 2026-02-22 -->

![Gemini SEO](screenshots/cover-image.jpeg?v=20260222a)

# Gemini SEO

Authentic Gemini port of the original Claude SEO project.

> Independent community project, not affiliated with or endorsed by OpenAI.  
> Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)

## Project Intent

`gemini-seo` is designed as a port, not a reinvention.

Porting principles:
- keep Claude SEO structure, logic, and behavior as close as possible
- only add Gemini-specific adaptations where platform differences require it
- avoid custom feature drift that changes core audit behavior

## What Is Included

Primary SEO skill coverage (matches Claude SEO scope):
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

Meta orchestrator skill:
- `seo` (top-level routing/orchestration skill)

Audit specialist agents:
- `seo-technical`
- `seo-content`
- `seo-schema`
- `seo-sitemap`
- `seo-performance`
- `seo-visual`

## Gemini-Specific Adaptation

The only intentional behavioral adaptation for audits is execution mapping:
- Claude subagent delegation maps to Gemini multi-agent delegation (`spawn_agent` + `wait`)
- In Gemini chat, `/seo audit` should default to this multi-agent path. Deterministic runners are for explicit CLI/reproducibility use cases.

Everything else should remain aligned with upstream Claude SEO skill intent and output structure.

## Gemini Multi-Agent Requirement (Important)

For authentic `/seo audit` behavior in Gemini chat, enable Gemini experimental multi-agent mode:

1. Run `/experimental` in Gemini.
2. Turn **Multi-agent** ON.
3. Start a new audit request.

Without this toggle enabled, Gemini chat may fall back to non-parallel behavior and produce less complete delegation patterns.

## Installation

### One-command install (Unix/macOS/Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/avalonreset/gemini-seo/main/install.sh | bash
```

### One-command install (Windows PowerShell)

```powershell
irm https://raw.githubusercontent.com/avalonreset/gemini-seo/main/install.ps1 | iex
```

### Manual install

```bash
git clone https://github.com/avalonreset/gemini-seo.git
cd gemini-seo
pip install -r requirements.txt
```

Copy skills to Gemini:

```bash
export Gemini_HOME="${Gemini_HOME:-$HOME/.Gemini}"
mkdir -p "$Gemini_HOME/skills/seo"
cp -r seo/* "$Gemini_HOME/skills/seo/"
for d in skills/*; do
  name="$(basename "$d")"
  mkdir -p "$Gemini_HOME/skills/$name"
  cp -r "$d/"* "$Gemini_HOME/skills/$name/"
done
mkdir -p "$Gemini_HOME/agents"
cp -r agents/* "$Gemini_HOME/agents/"
```

## Quick Start

Use normal Gemini prompts, for example:
- "Run a full SEO audit for https://example.com"
- "Analyze this page deeply: https://example.com/about"
- "Validate hreflang for https://example.com"
- "Generate a sitemap from this URL list"

Expected audit behavior:
1. fetches core pages
2. delegates to specialist agents in parallel (when Gemini multi-agent is enabled)
3. merges findings into `FULL-AUDIT-REPORT.md` and `ACTION-PLAN.md` (plus HTML/PDF artifacts in runner mode)

## Architecture

```text
seo/                            # Orchestrator skill + references
skills/seo-*/                   # primary skills + specialist audit runners
agents/seo-*.md                 # Specialist agent profiles
schema/templates.json           # Schema templates
```

## Documentation

- [Installation Guide](docs/INSTALLATION.md)
- [Release Notes v1.4.0](docs/RELEASE-NOTES-v1.4.0.md)
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
- Gemini port and maintenance: [avalonreset/gemini-seo](https://github.com/avalonreset/gemini-seo)

