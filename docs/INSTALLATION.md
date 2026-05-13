# Installation Guide

## Prerequisites

- Python 3.10+ with pip
- Git
- Optional: Playwright for screenshot and visual analysis workflows

## Quick Install

Unix, macOS, Linux:

```bash
git clone --depth 1 https://github.com/avalonreset/gemini-seo.git
bash gemini-seo/install.sh
```

Windows:

```powershell
git clone --depth 1 https://github.com/avalonreset/gemini-seo.git
powershell -ExecutionPolicy Bypass -File gemini-seo\install.ps1
```

The installer copies the root bundle, individual `skills/seo*` directories,
companion specialist notes, scripts, schema templates, docs, and optional
extensions into user-level skill directories.

The standard install path is the Gemini user skill root:

| Files | Install location |
|-------|------------------|
| Skills | `~/.gemini/skills/` |
| Companion specialist notes | `~/.gemini/agents/` |

## Release Tag Pinning

Installers clone the current release tag by default:

```bash
GEMINI_SEO_TAG=v1.9.9 bash gemini-seo/install.sh
```

Use `GEMINI_SEO_TAG=main` only when you intentionally want the latest branch tip.

## Packaged Skill Install

For Gemini CLI package installs, download `gemini-seo.skill` from the release
assets and run:

```bash
gemini skills install path/to/gemini-seo.skill --scope user
```

## Dependency Install

The installer creates a Python venv under each installed `seo` skill directory.
Disable automatic dependency installation with:

```bash
GEMINI_SEO_INSTALL_DEPS=0 bash gemini-seo/install.sh
```

Manual dependency install:

```bash
python -m pip install -r requirements.txt
```

Optional visual analysis support:

```bash
python -m playwright install chromium
```

## Verify

Check that the orchestrator exists in your selected skill root:

```bash
ls ~/.gemini/skills/seo/SKILL.md
```

Then run:

```text
/seo audit https://example.com
```

## Uninstall

Unix, macOS, Linux:

```bash
bash gemini-seo/uninstall.sh
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File gemini-seo\uninstall.ps1
```
