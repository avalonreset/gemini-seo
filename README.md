# Gemini SEO

A comprehensive suite of 14 professional-grade SEO analysis tools, running natively as a Gemini CLI Skill.

> Independent community project, not affiliated with or endorsed by Google.
> Original concept based on Claude SEO.

## What Makes Gemini SEO Special?

Unlike ports for other platforms that rely on cumbersome multi-agent spawning (like Codex or Claude), **Gemini SEO** takes full advantage of Gemini's native context management using a **Single Master Orchestrator** and **Progressive Disclosure Architecture**.

### 1. Single Master Orchestrator
There is only one skill file (`SKILL.md`). It acts as a highly efficient routing table. It doesn't load 14 massive rulesets at once, keeping Gemini's context window lightning fast and laser-focused. 

### 2. Progressive Disclosure
When you request a specific task (e.g., "Analyze the Schema on this page"), the Orchestrator dynamically loads only the exact tactical guide it needs (e.g., `references/seo-schema.md`), performs the deep analysis, and immediately drops it when finished. This ensures zero cross-contamination of instructions and massive token savings.

### 3. Built-In Premium Reporting
Every single one of the 14 SEO tools is wired into a premium reporting engine. While a full site audit generates this automatically, you can append "give me the premium deliverable" to *any* request (like a quick Core Web Vitals check or an E-E-A-T analysis). Gemini will intelligently adapt the master HTML/PDF template (`assets/report-template.html`) to match your specific request, instantly generating a $5,000-level agency deliverable.

## Features
- **Full Site Audit:** Generates premium HTML/PDF client deliverables.
- **Deep Single-Page Analysis:** On-page, technical, content quality.
- **E-E-A-T & Content Quality:** Evaluates signals, readability, depth.
- **Schema Markup:** Detects, validates, and generates JSON-LD.
- **Core Web Vitals & Performance:** Measures LCP, INP, CLS.
- **AI Search Readiness (GEO):** Optimizes for AI Overviews, ChatGPT, Perplexity.
- **Competitor Pages & Hreflang:** Validation and generation.
- **Programmatic SEO & Strategic Planning:** Actionable roadmaps.

## Installation

Gemini SEO is packaged as a standard Gemini CLI Skill.

1. Download the latest `gemini-seo.skill` file from the [Releases](#) page (or build it from source).
2. Install it using the Gemini CLI:
   ```bash
   gemini skills install path/to/gemini-seo.skill --scope user
   ```
3. Reload your active Gemini CLI session:
   ```bash
   /skills reload
   ```

## Usage

Use natural language prompts inside Gemini CLI to trigger workflows:
- "Run a full SEO audit for https://example.com"
- "Analyze this page deeply: https://example.com/about"
- "Validate hreflang for https://example.com"
- "Generate a sitemap from this URL list"

**Pro-Tip:** Ask for a "premium report" or "client deliverable" at the end of any prompt, and Gemini SEO will automatically format its findings into a highly polished, responsive HTML dashboard and PDF.

## Architecture

```text
gemini-seo/                     
├── SKILL.md                    # The Single Master Orchestrator
├── references/                 # 14 specialized tactical guides (loaded dynamically)
├── scripts/                    # Secure Python web-fetching & screenshot utilities
└── assets/                     # Premium HTML reporting templates
```

## Attribution

- Original project and concept: [AgriciDaniel/claude-seo](https://github.com/AgriciDaniel/claude-seo)
- Gemini Native Port: [avalonreset/gemini-seo](https://github.com/avalonreset/gemini-seo)