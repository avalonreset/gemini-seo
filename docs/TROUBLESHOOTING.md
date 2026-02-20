# Troubleshooting

## Skill Not Loading in Codex

**Symptom:** Codex does not pick the expected SEO skill.

### Checks

1. Verify skill files exist under your Codex home:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
ls "$CODEX_HOME/skills/seo/SKILL.md"
ls "$CODEX_HOME/skills/seo-audit/SKILL.md"
```

2. Ensure files were copied recursively (including `scripts/` and `assets/` directories).

3. Restart your Codex session after installing or updating skills.

## Python Dependency Errors

**Symptom:** `ModuleNotFoundError` (for example `requests`, `bs4`, `lxml`).

### Fix

```bash
pip install -r requirements.txt
```

If using a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Playwright Errors

**Symptom:** Browser executable missing or screenshot/visual checks fail.

### Fix

```bash
pip install playwright
python -m playwright install chromium
```

If unavailable, use `--visual off` where supported.

## Runner Command Fails

**Symptom:** Non-zero exit code from a `run_*.py` script.

### Checks

1. Confirm CLI syntax:

```bash
python skills/seo-audit/scripts/run_audit.py --help
```

2. Use explicit output directory:

```bash
python skills/seo-page/scripts/run_page_audit.py https://example.com --output-dir out/page
```

3. For URL-based scans, test network and certificate trust:

```bash
python -c "import requests; print(requests.get('https://example.com', timeout=10).status_code)"
```

## SSL Certificate Verification Errors

**Symptom:** `CERTIFICATE_VERIFY_FAILED`.

### Notes

- This is usually local trust-store configuration, proxy interception, or enterprise TLS middleware.
- It is not typically a skill logic bug.

### Fix paths

1. Update your OS/root certificate store.
2. Ensure Python uses current cert bundles.
3. Re-test with a known public domain after trust-store fixes.

## "URL blocked as non-public" Errors

**Symptom:** Runner refuses localhost/private/reserved hosts.

### Cause

Security guardrails intentionally block SSRF-style targets.

### Fix

- Use a public `http` or `https` URL.
- For local testing, use `--html-file` mode where available (`seo-geo`, `seo-images`, `seo-schema`, `seo-hreflang`, `seo-sitemap`).

## Slow Full Audits

**Symptom:** Full audit takes longer than expected.

### Notes

- Large sites increase crawl duration.
- Optional visual checks add runtime cost.
- Network latency and origin throttling affect total runtime.

### Fast-path options

1. Lower crawl size (`--max-pages` on full audit)
2. Disable visuals (`--visual off`)
3. Run targeted skills first (`seo-page`, `seo-technical`, `seo-content`)

## Still Stuck

Provide:

1. Exact command used
2. Full stderr output
3. Your Python version (`python --version`)
4. Whether you ran inside a virtual environment
