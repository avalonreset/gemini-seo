<!-- Updated: 2026-02-22 -->

![Gemini SEO](screenshots/cover-image.jpeg?v=20260222a)

# Gemini SEO

A comprehensive suite of 14 professional-grade SEO analysis workflows, running natively inside the Gemini CLI.

> Independent community project, not affiliated with or endorsed by Google.  
> Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)

## Project Intent

`gemini-seo` is a Gemini-native adaptation of Claude SEO's methodology, tuned for Gemini CLI behavior and context handling.

Adaptation principles:
- Preserve the original strategic SEO coverage while adapting execution for Gemini workflows.
- Use **Progressive Disclosure** so only the needed reference guide is loaded per request.
- Route everything through a **Single Master Orchestrator** (`SKILL.md`) for speed and context control.
- Support premium client-ready deliverables via HTML and PDF reporting templates.

## What Is Included

Primary workflow coverage (14):
- `seo-audit` - full-site auditing
- `seo-page` - deep single-page analysis
- `seo-technical` - technical SEO review
- `seo-content` - E-E-A-T and quality analysis
- `seo-schema` - schema detection/validation/generation
- `seo-images` - image SEO and performance analysis
- `seo-sitemap` - sitemap audit/generation
- `seo-geo` - AI search and citation readiness
- `seo-plan` - strategic SEO planning
- `seo-programmatic` - pages-at-scale analysis
- `seo-competitor-pages` - comparison/alternatives strategy
- `seo-hreflang` - international SEO validation
- `seo-performance` - Core Web Vitals/performance checks
- `seo-visual` - screenshot and visual-first diagnostics

All workflows are orchestrated by:
- `gemini-seo` - top-level routing/orchestration skill

## Why Gemini SEO Works

### 1. Single Master Orchestrator
`SKILL.md` acts as a compact router that delegates to exact references only when needed.

### 2. Progressive Disclosure
Each request pulls only the relevant tactical file (for example `references/seo-schema.md`), avoiding unnecessary context bloat.

### 3. Built-In Premium Reporting
Every workflow can output a polished report format using `assets/report-template.html`.  
When requested, outputs can be packaged as both HTML and PDF deliverables.

## Installation

Gemini SEO is packaged as a standard Gemini CLI Skill.

1. Download the latest `gemini-seo.skill` file from the [Releases](https://github.com/avalonreset/gemini-seo/releases) page.
2. Install it using the Gemini CLI:
   ```bash
   gemini skills install path/to/gemini-seo.skill --scope user
   ```
3. Reload your active Gemini CLI session:
   ```bash
   /skills reload
   ```
4. Optional verification:
   ```bash
   /skills list
   ```

## Quick Start

Use natural language prompts inside the Gemini CLI, for example:
- "Run a full SEO audit for https://example.com"
- "Analyze this page deeply: https://example.com/about"
- "Validate hreflang for https://example.com"
- "Generate a sitemap from this URL list"

Tip: append "premium report" or "client deliverable" to any request to generate polished report outputs.

## Output Artifacts

Depending on task type, Gemini SEO can produce:
- `FULL-AUDIT-REPORT.md`
- `ACTION-PLAN.md`
- `CLIENT-SEO-AUDIT.html`
- `CLIENT-SEO-AUDIT.pdf`
- Supporting screenshots and analysis files when applicable

## Architecture

```text
gemini-seo/                     
├── SKILL.md                    # The Single Master Orchestrator
├── references/                 # 14 specialized tactical guides (loaded dynamically)
├── scripts/                    # Secure Python web-fetching & screenshot utilities
└── assets/                     # Premium HTML reporting templates
```

## Documentation

- [Installation Guide](docs/INSTALLATION.md)
- [Workflow Reference](docs/COMMANDS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Legal Notice](LEGAL-NOTICE.md)

## License

MIT License. See [LICENSE](LICENSE).

## Attribution

- Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)
- Gemini Native Port: [avalonreset/gemini-seo](https://github.com/avalonreset/gemini-seo)

## Community

If you want deeper tactical training, templates, and live implementation breakdowns, you can join:
**[AI Marketing Hub Pro](https://www.skool.com/ai-marketing-hub-pro/about?ref=59f96e9d9f2b4047b53627692d8c8f0c)**

Disclosure: The link above is a referral link. If you join through it, I may receive a commission at no additional cost to you.
