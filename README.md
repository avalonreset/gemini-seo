<p align="center">
  <img src="screenshots/cover-image.webp" alt="Gemini SEO, open source SEO tools for Gemini CLI with 14 professional analysis workflows" width="100%">
</p>

# Gemini SEO: Open Source SEO Tools for Gemini CLI

[![CI](https://github.com/avalonreset/gemini-seo/actions/workflows/runners-ci.yml/badge.svg)](https://github.com/avalonreset/gemini-seo/actions/workflows/runners-ci.yml)
[![Version](https://img.shields.io/github/v/release/avalonreset/gemini-seo)](https://github.com/avalonreset/gemini-seo/releases)
[![License](https://img.shields.io/github/license/avalonreset/gemini-seo)](LICENSE)

Most open source SEO tools are web apps that require hosting, databases, and ongoing maintenance. Gemini SEO takes a different approach: 14 professional-grade SEO analysis workflows, 6 multi-agent runners, and client-ready reporting that run directly inside the Gemini CLI with zero infrastructure. Just install the skill and start auditing.

> Independent community project, not affiliated with or endorsed by Google.
> Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)

## Table of Contents

- [SEO Workflows and Commands](#seo-workflows-and-commands)
- [How It Works](#how-it-works)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Output Artifacts](#output-artifacts)
- [Architecture](#architecture)
- [Documentation](#documentation)
- [Attribution](#attribution)
- [FAQ](#faq)
- [Community](#community)
- [License](#license)

## SEO Workflows and Commands

Gemini SEO provides 14 SEO audit and analysis workflows, all orchestrated through a single master skill file:

| Workflow | What It Does |
|----------|-------------|
| `seo-audit` | Full-site health check across all SEO dimensions |
| `seo-page` | Deep single-page analysis (on-page, meta, content) |
| `seo-technical` | Crawlability, indexability, Core Web Vitals, security |
| `seo-content` | E-E-A-T evaluation, readability, content depth |
| `seo-schema` | Schema.org detection, validation, and JSON-LD generation |
| `seo-images` | Alt text, file sizes, formats, responsive attributes |
| `seo-sitemap` | XML sitemap audit and generation |
| `seo-geo` | AI search readiness (Google AI Overviews, ChatGPT, Perplexity) |
| `seo-plan` | Strategic SEO planning and content roadmaps |
| `seo-programmatic` | Scaled-page analysis for thin content and index bloat |
| `seo-competitor-pages` | Comparison and alternatives page strategy |
| `seo-hreflang` | International SEO and hreflang validation |
| `seo-performance` | Core Web Vitals (LCP, INP, CLS) measurement |
| `seo-visual` | Screenshot capture and visual diagnostics |

## How It Works

### Single Master Orchestrator
`SKILL.md` acts as a compact router that delegates to the exact reference guide needed for each request. No wasted context, no loading unnecessary files.

### Progressive Disclosure
Each request pulls only the relevant tactical file (for example `references/seo-schema.md`), keeping context usage minimal even across complex multi-step audits.

### Built-In Premium Reporting
Every workflow can output polished client-ready deliverables using `assets/report-template.html`. Outputs can be packaged as both HTML and PDF reports.

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
4. Verify the installation:
   ```bash
   /skills list
   ```
   You should see `gemini-seo` in the output with all 14 workflows available.

## Quick Start

Use natural language prompts inside the Gemini CLI:

```
Run a full SEO audit for https://example.com
```

The audit workflow fetches the page, analyzes on-page elements, checks technical SEO signals, evaluates content quality against E-E-A-T criteria, and produces a scored report with prioritized action items.

More examples:
- `Analyze this page deeply: https://example.com/about`
- `Validate hreflang for https://example.com`
- `Generate a sitemap from this URL list`

Append "premium report" or "client deliverable" to any request to generate polished HTML/PDF output.

## Output Artifacts

Depending on the task, Gemini SEO can produce:

| Output | Description |
|--------|-------------|
| `FULL-AUDIT-REPORT.md` | Complete site audit with scores and action items |
| `ACTION-PLAN.md` | Prioritized SEO improvement roadmap |
| `CLIENT-SEO-AUDIT.html` | Branded HTML report for client delivery |
| `CLIENT-SEO-AUDIT.pdf` | PDF version of the client report |

## Architecture

```text
gemini-seo/
├── SKILL.md                    # Single Master Orchestrator (routing + delegation)
├── references/                 # 14 specialized tactical guides (loaded on demand)
├── scripts/                    # Python utilities (fetch, parse, screenshot, analyze)
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

## Attribution

- Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)
- Original Claude SEO demo: [Watch on YouTube](https://www.youtube.com/watch?v=COMnNlUakQk)

## FAQ

### What does Gemini SEO do?

Gemini SEO is a collection of 14 SEO analysis workflows that run inside the Gemini CLI. It performs full-site audits, technical SEO checks, schema validation, content quality scoring, and AI search readiness analysis without requiring a web app or external service.

### How is this different from other SEO tools?

Traditional SEO tools like Screaming Frog or Ahrefs run as standalone applications or cloud services. Gemini SEO runs directly in your terminal as a CLI skill, loading only the specific analysis needed for each request. No browser, no subscription, no infrastructure.

### Does this work with Google AI Overviews and ChatGPT?

Yes. The `seo-geo` workflow specifically analyzes your site's readiness for AI-powered search, including Google AI Overviews, ChatGPT web search, and Perplexity. It checks AI crawler accessibility, passage-level citability, and structured data signals.

## Community

Join [AI Marketing Hub Pro](https://www.skool.com/ai-marketing-hub-pro/about?ref=59f96e9d9f2b4047b53627692d8c8f0c) for access to exclusive projects (referral link).

**Other projects:**

> **[codex-seo](https://github.com/avalonreset/codex-seo)** - Same firepower, built for Codex CLI. 12 workflows, 6 parallel agents, client-ready HTML/PDF reports from your terminal.

> **[wan2gp-operator](https://github.com/avalonreset/wan2gp-operator)** - CLI operator for Wan2GP text-to-video. VRAM-aware compose, headless batch runs, auto-retry, and a music video pipeline that turns audio into beat-synced AI videos.

> **[BenjaminTerm](https://github.com/avalonreset/BenjaminTerm)** - Hacker-styled WezTerm distribution for Windows. Smart clipboard, paste undo, 86 curated dark themes with shuffle-bag rotation, borderless glass mode.

## License

MIT License. See [LICENSE](LICENSE).
