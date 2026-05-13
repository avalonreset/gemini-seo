# Troubleshooting

## Skill Not Loading

Verify the orchestrator exists in the skill root you installed to:

```bash
ls ~/.gemini/skills/seo/SKILL.md
ls ~/.codex/skills/seo/SKILL.md
ls ~/.claude/skills/seo/SKILL.md
```

Check frontmatter:

```bash
head -5 ~/.gemini/skills/seo/SKILL.md
```

Then restart the host agent and re-run `/seo`.

## Python Dependency Errors

If a script raises `ModuleNotFoundError`, reinstall dependencies into the venv
created under the installed `seo` skill directory:

```bash
~/.gemini/skills/seo/.venv/bin/pip install -r ~/.gemini/skills/seo/requirements.txt
```

Fallback:

```bash
python -m pip install --user -r requirements.txt
```

## Playwright Screenshot Errors

Install Chromium for visual analysis:

```bash
python -m playwright install chromium
```

Without Playwright, visual workflows can still use fetch-based fallbacks, but
screenshot and above-the-fold checks are limited.

## Permission Denied

Make helper scripts executable on Unix-like systems:

```bash
chmod +x ~/.gemini/skills/seo/scripts/*.py
```

## Companion Agent Notes Missing

Verify the installed agent notes:

```bash
ls ~/.gemini/agents/seo-*.md
ls ~/.codex/agents/seo-*.md
ls ~/.claude/agents/seo-*.md
```

Re-run the installer if they are absent.

## URL Fetch Fails

- Confirm the URL is public and reachable.
- Some sites block automated requests.
- Use `scripts/fetch_page.py` directly for lower-level diagnostics:

```bash
python scripts/fetch_page.py https://example.com
```

## Schema Validation False Positives

- Ensure placeholders are replaced.
- Verify `@context` is `https://schema.org`.
- Check for deprecated types such as `HowTo` and `SpecialAnnouncement`.
- Validate externally with Google's Rich Results Test when needed.

## Large Audits Are Slow

Full audits can inspect many URLs and run several specialist passes. For faster
triage, run `/seo page <url>` or the specific sub-command that matches the
suspected problem.
