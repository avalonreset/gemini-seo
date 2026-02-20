# Installation Guide

## Prerequisites

- Python 3.8+ with pip
- Git
- Codex CLI/runtime configured on your machine

Optional:
- Playwright for visual checks (`python -m playwright install chromium`)

## Install Repository

```bash
git clone https://github.com/avalonreset/codex-seo.git
cd codex-seo
```

## Install Python Dependencies

```bash
pip install -r requirements.txt
```

For isolated installs, use a virtual environment:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Install Skills Into Codex

### Linux/macOS

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills/seo"
cp -r seo/* "$CODEX_HOME/skills/seo/"

for d in skills/*; do
  name="$(basename "$d")"
  mkdir -p "$CODEX_HOME/skills/$name"
  cp -r "$d/"* "$CODEX_HOME/skills/$name/"
done
```

### Windows (PowerShell)

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$env:USERPROFILE\\.codex" }
New-Item -ItemType Directory -Force -Path "$codexHome\\skills\\seo" | Out-Null
Copy-Item -Recurse -Force "seo\\*" "$codexHome\\skills\\seo\\"
Get-ChildItem -Directory skills | ForEach-Object {
  $target = "$codexHome\\skills\\$($_.Name)"
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  Copy-Item -Recurse -Force "$($_.FullName)\\*" $target
}
```

## Optional: Install Agent Profiles

If you want local reference prompts for specialist agents:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/agents"
cp -r agents/*.md "$CODEX_HOME/agents/"
```

PowerShell:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$env:USERPROFILE\\.codex" }
New-Item -ItemType Directory -Force -Path "$codexHome\\agents" | Out-Null
Copy-Item -Force "agents\\*.md" "$codexHome\\agents\\"
```

## Verify Installation

1. Confirm skills are present:

```bash
ls "$CODEX_HOME/skills/seo/SKILL.md"
ls "$CODEX_HOME/skills/seo-audit/SKILL.md"
```

2. Run a deterministic smoke check:

```bash
python skills/seo-audit/scripts/run_audit.py --help
python skills/seo-page/scripts/run_page_audit.py --help
```

3. Start Codex and ask for a workflow:

- "Run a technical SEO audit for https://example.com"
- "Generate hreflang tags from this mapping JSON"

## Uninstall

Remove installed skill directories from `$CODEX_HOME/skills`:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
rm -rf "$CODEX_HOME/skills/seo"
for skill in seo-audit seo-competitor-pages seo-content seo-geo seo-hreflang seo-images seo-page seo-plan seo-programmatic seo-schema seo-sitemap seo-technical; do
  rm -rf "$CODEX_HOME/skills/$skill"
done
```

PowerShell:

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$env:USERPROFILE\\.codex" }
Remove-Item -Recurse -Force "$codexHome\\skills\\seo" -ErrorAction SilentlyContinue
@(
  "seo-audit","seo-competitor-pages","seo-content","seo-geo","seo-hreflang","seo-images",
  "seo-page","seo-plan","seo-programmatic","seo-schema","seo-sitemap","seo-technical"
) | ForEach-Object {
  Remove-Item -Recurse -Force "$codexHome\\skills\\$_" -ErrorAction SilentlyContinue
}
```
