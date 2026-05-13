---
name: gemini-seo
description: Comprehensive SEO analysis for audits, technical SEO, schema, content quality, GEO, local SEO, backlinks, e-commerce, international SEO, and reporting. Routes to the /seo orchestrator and specialized sub-skills.
metadata:
  version: "1.9.9"
  category: seo
---

# Gemini SEO

This root skill is a compatibility wrapper. For all SEO work, read
`skills/seo/SKILL.md` first and follow its routing instructions.

The project includes 25 sub-skills, 18 companion specialist instructions, and
30 Python execution scripts. Do not load everything at startup. Use progressive
disclosure:

1. Determine the user's SEO intent.
2. Read `skills/seo/SKILL.md`.
3. Load only the relevant `skills/seo-*/SKILL.md` file and referenced materials.
4. Use scripts in `scripts/` when live fetching, parsing, screenshots, API calls,
   drift baselines, backlink checks, or reports are required.

Primary commands are exposed as `/seo ...` workflows.
