# Installation Guide

## Prerequisites

- **Python 3.8+** with pip
- **Git** for cloning the repository
- **Codex CLI** installed and configured

Optional:
- **Playwright** for screenshot capabilities

## Quick Install

### Unix/macOS/Linux

```bash
curl -fsSL https://raw.githubusercontent.com/AgriciDaniel/Codex-seo/main/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/AgriciDaniel/Codex-seo/main/install.ps1 | iex
```

## Manual Installation

1. **Clone the repository**

```bash
git clone https://github.com/AgriciDaniel/Codex-seo.git
cd Codex-seo
```

2. **Run the installer**

```bash
./install.sh
```

3. **Install Python dependencies** (if not done automatically)

The installer creates a venv at `~/.Codex/skills/seo/.venv/`. If that fails, install manually:

```bash
# Option A: Use the venv
~/.Codex/skills/seo/.venv/bin/pip install -r ~/.Codex/skills/seo/requirements.txt

# Option B: User-level install
pip install --user -r ~/.Codex/skills/seo/requirements.txt
```

4. **Install Playwright browsers** (optional, for visual analysis)

```bash
pip install playwright
playwright install chromium
```

Playwright is optional — without it, visual analysis uses WebFetch as a fallback.

## Installation Paths

The installer copies files to:

| Component | Path |
|-----------|------|
| Main skill | `~/.Codex/skills/seo/` |
| Sub-skills | `~/.Codex/skills/seo-*/` |
| multi-agents | `~/.Codex/agents/seo-*.md` |

## Verify Installation

1. Start Codex:

```bash
Codex
```

2. Check that the skill is loaded:

```
/seo
```

You should see a help message or prompt for a URL.

## Uninstallation

```bash
curl -fsSL https://raw.githubusercontent.com/AgriciDaniel/Codex-seo/main/uninstall.sh | bash
```

Or manually:

```bash
rm -rf ~/.Codex/skills/seo
rm -rf ~/.Codex/skills/seo-audit
rm -rf ~/.Codex/skills/seo-competitor-pages
rm -rf ~/.Codex/skills/seo-content
rm -rf ~/.Codex/skills/seo-geo
rm -rf ~/.Codex/skills/seo-hreflang
rm -rf ~/.Codex/skills/seo-images
rm -rf ~/.Codex/skills/seo-page
rm -rf ~/.Codex/skills/seo-plan
rm -rf ~/.Codex/skills/seo-programmatic
rm -rf ~/.Codex/skills/seo-schema
rm -rf ~/.Codex/skills/seo-sitemap
rm -rf ~/.Codex/skills/seo-technical
rm -f ~/.Codex/agents/seo-*.md
```

## Upgrading

To upgrade to the latest version:

```bash
# Uninstall current version
curl -fsSL https://raw.githubusercontent.com/AgriciDaniel/Codex-seo/main/uninstall.sh | bash

# Install new version
curl -fsSL https://raw.githubusercontent.com/AgriciDaniel/Codex-seo/main/install.sh | bash
```

## Troubleshooting

### "Skill not found" error

Ensure the skill is installed in the correct location:

```bash
ls ~/.Codex/skills/seo/SKILL.md
```

If the file doesn't exist, re-run the installer.

### Python dependency errors

Install dependencies manually:

```bash
pip install beautifulsoup4 requests lxml playwright Pillow urllib3 validators
```

### Playwright screenshot errors

Install Chromium browser:

```bash
playwright install chromium
```

### Permission errors on Unix

Make sure scripts are executable:

```bash
chmod +x ~/.Codex/skills/seo/scripts/*.py
chmod +x ~/.Codex/skills/seo/hooks/*.py
chmod +x ~/.Codex/skills/seo/hooks/*.sh
```

