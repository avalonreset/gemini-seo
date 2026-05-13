# Gemini SEO manual-install uninstaller for Windows

$ErrorActionPreference = "Stop"

function Remove-Target {
    param(
        [Parameter(Mandatory = $true)][string]$SkillRoot,
        [Parameter(Mandatory = $true)][string]$AgentRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $removedSkills = 0
    $removedAgents = 0

    foreach ($path in @((Join-Path $SkillRoot "gemini-seo"), (Join-Path $SkillRoot "seo"))) {
        if (Test-Path $path) {
            Remove-Item -Recurse -Force $path
            $removedSkills++
        }
    }

    if (Test-Path $SkillRoot) {
        Get-ChildItem -Path $SkillRoot -Directory -Filter "seo-*" | ForEach-Object {
            Remove-Item -Recurse -Force $_.FullName
            $removedSkills++
        }
    }

    if (Test-Path $AgentRoot) {
        Get-ChildItem -Path $AgentRoot -File -Filter "seo-*.md" | ForEach-Object {
            Remove-Item -Force $_.FullName
            $removedAgents++
        }
    }

    Write-Host "$Label: removed $removedSkills skill dirs and $removedAgents agent files."
}

$Targets = if ($env:GEMINI_SEO_TARGETS) { $env:GEMINI_SEO_TARGETS } else { "gemini,codex,claude" }

foreach ($target in $Targets.Split(",")) {
    $target = $target.Trim().ToLowerInvariant()
    switch ($target) {
        "gemini" {
            Remove-Target -SkillRoot (Join-Path $env:USERPROFILE ".gemini\skills") -AgentRoot (Join-Path $env:USERPROFILE ".gemini\agents") -Label "gemini"
        }
        "codex" {
            $codexBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
            Remove-Target -SkillRoot (Join-Path $codexBase "skills") -AgentRoot (Join-Path $codexBase "agents") -Label "codex"
        }
        "claude" {
            Remove-Target -SkillRoot (Join-Path $env:USERPROFILE ".claude\skills") -AgentRoot (Join-Path $env:USERPROFILE ".claude\agents") -Label "claude"
        }
        "" {}
        default { throw "Unknown target '$target'." }
    }
}
