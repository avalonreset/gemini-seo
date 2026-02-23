# Gemini SEO

A comprehensive suite of 12+ professional-grade SEO analysis tools, running natively as a Gemini CLI Skill.

> Independent community project, not affiliated with or endorsed by Google.
> Original concept based on Claude SEO.

## Features
- **Full Site Audit:** Generates premium HTML/PDF client deliverables.
- **Deep Single-Page Analysis:** On-page, technical, content quality.
- **E-E-A-T & Content Quality:** Evaluates signals, readability, depth.
- **Schema Markup:** Detects, validates, and generates JSON-LD.
- **Core Web Vitals & Performance:** Measures LCP, INP, CLS.
- **AI Search Readiness (GEO):** Optimizes for AI Overviews, ChatGPT, Perplexity.
- **Competitor Pages & Hreflang:** Validation and generation.

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

If you request a "premium report" or "client deliverable," Gemini SEO will automatically format its findings into a highly polished, responsive HTML dashboard and PDF.

## Architecture
Gemini SEO utilizes the official Gemini **Progressive Disclosure** architecture. 
- `SKILL.md` acts as the ultra-lean orchestrator.
- `references/` contains 12 domain-specific tactical guides that are loaded dynamically on demand.
- `assets/` contains premium reporting templates.
- `scripts/` contains secure Python web-fetching utilities.