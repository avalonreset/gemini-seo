# Gemini SEO Installer for Windows

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Gemini SEO - Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Resolve-Python {
    $pythonCmd = Get-Command -Name python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCmd) { return @{ Exe = "python"; Args = @() } }

    $pyCmd = Get-Command -Name py -ErrorAction SilentlyContinue
    if ($null -ne $pyCmd) { return @{ Exe = "py"; Args = @("-3") } }

    return $null
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Args,
        [switch]$Quiet
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $hasNativePreference = $null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)
    if ($hasNativePreference) { $previousNativePreference = $PSNativeCommandUseErrorActionPreference }

    try {
        $ErrorActionPreference = "Continue"
        if ($hasNativePreference) { $PSNativeCommandUseErrorActionPreference = $false }
        $output = & $Exe @Args 2>&1 | ForEach-Object { $_.ToString() }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($hasNativePreference) { $PSNativeCommandUseErrorActionPreference = $previousNativePreference }
    }

    if (-not $Quiet -and $null -ne $output -and $output.Count -gt 0) {
        $output | ForEach-Object { Write-Host $_ }
    }

    return @{ ExitCode = $exitCode; Output = $output }
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Copy-Item -Recurse -Force -Path (Join-Path $Source "*") -Destination $Destination
}

function Install-Target {
    param(
        [Parameter(Mandatory = $true)][string]$RepoDir,
        [Parameter(Mandatory = $true)][string]$SkillRoot,
        [Parameter(Mandatory = $true)][string]$AgentRoot,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)]$Python
    )

    Write-Host "Installing $Label skill files into $SkillRoot..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $SkillRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $AgentRoot | Out-Null

    $bundleDir = Join-Path $SkillRoot "gemini-seo"
    if (Test-Path $bundleDir) { Remove-Item -Recurse -Force $bundleDir }
    New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null
    Copy-Item -Force -LiteralPath (Join-Path $RepoDir "SKILL.md") -Destination $bundleDir
    foreach ($dir in @("skills","agents","scripts","schema","docs","extensions","hooks","pdf","tests")) {
        $source = Join-Path $RepoDir $dir
        if (Test-Path $source) {
            Copy-Item -Recurse -Force -LiteralPath $source -Destination (Join-Path $bundleDir $dir)
        }
    }
    $reqFile = Join-Path $RepoDir "requirements.txt"
    if (Test-Path $reqFile) { Copy-Item -Force $reqFile (Join-Path $bundleDir "requirements.txt") }

    $skillsPath = Join-Path $RepoDir "skills"
    Get-ChildItem -Directory $skillsPath | ForEach-Object {
        $target = Join-Path $SkillRoot $_.Name
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        Copy-Item -Recurse -Force -Path (Join-Path $_.FullName "*") -Destination $target
    }

    $seoDir = Join-Path $SkillRoot "seo"
    foreach ($dir in @("scripts","schema","hooks","pdf","extensions")) {
        $source = Join-Path $RepoDir $dir
        if (Test-Path $source) {
            $dest = Join-Path $seoDir $dir
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Copy-Item -Recurse -Force -Path (Join-Path $source "*") -Destination $dest
        }
    }
    if (Test-Path $reqFile) { Copy-Item -Force $reqFile (Join-Path $seoDir "requirements.txt") }

    $agentsPath = Join-Path $RepoDir "agents"
    if (Test-Path $agentsPath) {
        Copy-Item -Force (Join-Path $agentsPath "*.md") $AgentRoot -ErrorAction SilentlyContinue
    }

    if (($env:GEMINI_SEO_INSTALL_DEPS -ne "0") -and (Test-Path $reqFile)) {
        $venvDir = Join-Path $seoDir ".venv"
        $venv = Invoke-External -Exe $Python.Exe -Args @($Python.Args + @("-m","venv",$venvDir)) -Quiet
        if ($venv.ExitCode -eq 0) {
            $pipExe = Join-Path $venvDir "Scripts\pip.exe"
            $pip = Invoke-External -Exe $pipExe -Args @("install","--quiet","-r",$reqFile) -Quiet
            if ($pip.ExitCode -ne 0) {
                Write-Host "Dependency install failed for $Label. Retry: $pipExe install -r $(Join-Path $seoDir 'requirements.txt')" -ForegroundColor Yellow
            }
        } else {
            $pip = Invoke-External -Exe $Python.Exe -Args @($Python.Args + @("-m","pip","install","--quiet","--user","-r",$reqFile)) -Quiet
            if ($pip.ExitCode -ne 0) {
                Write-Host "Dependency install failed for $Label. Retry: $($Python.Exe) -m pip install --user -r $(Join-Path $seoDir 'requirements.txt')" -ForegroundColor Yellow
            }
        }
    }
}

$python = Resolve-Python
if ($null -eq $python) {
    Write-Host "Python 3.10+ is required but was not found." -ForegroundColor Red
    exit 1
}

try {
    git --version | Out-Null
} catch {
    Write-Host "Git is required but not installed." -ForegroundColor Red
    exit 1
}

$RepoUrl = if ($env:GEMINI_SEO_REPO_URL) { $env:GEMINI_SEO_REPO_URL } else { "https://github.com/avalonreset/gemini-seo" }
$RepoTag = if ($env:GEMINI_SEO_TAG) { $env:GEMINI_SEO_TAG } else { 'v1.9.9' }
$Targets = if ($env:GEMINI_SEO_TARGETS) { $env:GEMINI_SEO_TARGETS } else { "gemini" }

$TempDir = Join-Path $env:TEMP "gemini-seo-install"
if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }

try {
    $clone = Invoke-External -Exe "git" -Args @("clone","--depth","1","--branch",$RepoTag,$RepoUrl,$TempDir) -Quiet
    if ($clone.ExitCode -ne 0) {
        throw "git clone failed. Output:`n$($clone.Output -join "`n")"
    }

    foreach ($target in $Targets.Split(",")) {
        $target = $target.Trim().ToLowerInvariant()
        switch ($target) {
            "gemini" {
                Install-Target -RepoDir $TempDir -SkillRoot (Join-Path $env:USERPROFILE ".gemini\skills") -AgentRoot (Join-Path $env:USERPROFILE ".gemini\agents") -Label "gemini" -Python $python
            }
            "codex" {
                $codexBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
                Install-Target -RepoDir $TempDir -SkillRoot (Join-Path $codexBase "skills") -AgentRoot (Join-Path $codexBase "agents") -Label "codex" -Python $python
            }
            "claude" {
                Install-Target -RepoDir $TempDir -SkillRoot (Join-Path $env:USERPROFILE ".claude\skills") -AgentRoot (Join-Path $env:USERPROFILE ".claude\agents") -Label "claude" -Python $python
            }
            "" {}
            default { throw "Unknown target '$target'. Check GEMINI_SEO_TARGETS." }
        }
    }

    Write-Host ""
    Write-Host "Gemini SEO installed successfully." -ForegroundColor Green
    Write-Host "Run an SEO workflow with: /seo audit https://example.com"
} finally {
    if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }
}
