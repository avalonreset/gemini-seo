# Codex SEO Installer for Windows
# PowerShell installation script

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Codex SEO - Installer" -ForegroundColor Cyan
Write-Host "  Codex Skill Suite" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Resolve-Python {
    $pythonCmd = Get-Command -Name python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCmd) {
        return @{ Exe = 'python'; Args = @() }
    }

    $pyCmd = Get-Command -Name py -ErrorAction SilentlyContinue
    if ($null -ne $pyCmd) {
        return @{ Exe = 'py'; Args = @('-3') }
    }

    return $null
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Args,
        [switch]$Quiet
    )

    $stdoutPath = [System.IO.Path]::GetTempFileName()
    $stderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $process = Start-Process `
            -FilePath $Exe `
            -ArgumentList $Args `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutPath `
            -RedirectStandardError $stderrPath

        $stdout = if (Test-Path $stdoutPath) { Get-Content -Path $stdoutPath -Raw } else { "" }
        $stderr = if (Test-Path $stderrPath) { Get-Content -Path $stderrPath -Raw } else { "" }
        $combined = @($stdout, $stderr) -join ""
        $output = if ([string]::IsNullOrWhiteSpace($combined)) { @() } else { $combined -split "`r?`n" }
        $exitCode = $process.ExitCode
    } finally {
        Remove-Item -Force $stdoutPath, $stderrPath -ErrorAction SilentlyContinue
    }

    if (-not $Quiet -and $null -ne $output -and $output.Count -gt 0) {
        $output | ForEach-Object { Write-Host $_ }
    }

    return @{ ExitCode = $exitCode; Output = $output }
}

# Check prerequisites
$python = Resolve-Python
if ($null -eq $python) {
    Write-Host "[ERROR] Python is required but was not found (tried 'python' and 'py')." -ForegroundColor Red
    exit 1
}

try {
    $pythonVersion = & $python.Exe @($python.Args + @('--version')) 2>&1
    Write-Host "[OK] $pythonVersion detected" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python is installed but could not be executed." -ForegroundColor Red
    exit 1
}

try {
    git --version | Out-Null
    Write-Host "[OK] Git detected" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Git is required but not installed." -ForegroundColor Red
    exit 1
}

# Set paths
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$env:USERPROFILE\.codex" }
$SkillDir = "$CodexHome\skills\seo"
$AgentDir = "$CodexHome\agents"
$RepoUrl = "https://github.com/avalonreset/codex-seo"

# Create directories
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
New-Item -ItemType Directory -Force -Path $AgentDir | Out-Null

# Clone to temp directory
$TempDir = Join-Path $env:TEMP "codex-seo-install"
if (Test-Path $TempDir) {
    Remove-Item -Recurse -Force $TempDir
}

$keepTemp = ($env:CODEX_SEO_KEEP_TEMP -eq '1')

try {
    Write-Host "[INFO] Downloading Codex SEO..." -ForegroundColor Yellow
    $clone = Invoke-External -Exe 'git' -Args @('clone','--depth','1',$RepoUrl,$TempDir) -Quiet
    if ($clone.ExitCode -ne 0) {
        throw "git clone failed. Output:`n$($clone.Output -join "`n")"
    }

    # Copy skill files
    Write-Host "[INFO] Installing skill files..." -ForegroundColor Yellow
    $skillSource = Join-Path $TempDir 'seo'
    if (-not (Test-Path $skillSource)) {
        $skillSource = Join-Path $TempDir 'skills\seo'
    }
    if (-not (Test-Path $skillSource)) {
        throw "Could not find skill source folder in repo clone."
    }
    Copy-Item -Recurse -Force (Join-Path $skillSource '*') $SkillDir

    # Copy sub-skills
    $SkillsPath = "$TempDir\skills"
    if (Test-Path $SkillsPath) {
        Get-ChildItem -Directory $SkillsPath | ForEach-Object {
            $target = "$CodexHome\skills\$($_.Name)"
            New-Item -ItemType Directory -Force -Path $target | Out-Null
            Copy-Item -Recurse -Force "$($_.FullName)\*" $target
        }
    }

    # Copy schema templates
    $SchemaPath = "$TempDir\schema"
    if (Test-Path $SchemaPath) {
        $SkillSchema = "$SkillDir\schema"
        New-Item -ItemType Directory -Force -Path $SkillSchema | Out-Null
        Copy-Item -Recurse -Force "$SchemaPath\*" $SkillSchema
    }

    # Copy reference docs
    $PdfPath = "$TempDir\pdf"
    if (Test-Path $PdfPath) {
        $SkillPdf = "$SkillDir\pdf"
        New-Item -ItemType Directory -Force -Path $SkillPdf | Out-Null
        Copy-Item -Recurse -Force "$PdfPath\*" $SkillPdf
    }

    # Copy agents
    Write-Host "[INFO] Installing agent profiles..." -ForegroundColor Yellow
    $AgentsPath = Join-Path $TempDir 'agents'
    if (Test-Path $AgentsPath) {
        Copy-Item -Force (Join-Path $AgentsPath '*.md') $AgentDir -ErrorAction SilentlyContinue
    }

    # Copy shared scripts
    $ScriptsPath = "$TempDir\scripts"
    if (Test-Path $ScriptsPath) {
        $SkillScripts = "$SkillDir\scripts"
        New-Item -ItemType Directory -Force -Path $SkillScripts | Out-Null
        Copy-Item -Recurse -Force "$ScriptsPath\*" $SkillScripts
    }

    # Copy hooks
    $HooksPath = "$TempDir\hooks"
    if (Test-Path $HooksPath) {
        $SkillHooks = "$SkillDir\hooks"
        New-Item -ItemType Directory -Force -Path $SkillHooks | Out-Null
        Copy-Item -Recurse -Force "$HooksPath\*" $SkillHooks
    }

    # Copy requirements.txt to skill dir for retry
    $reqFile = Join-Path $TempDir 'requirements.txt'
    $installedReqFile = Join-Path $SkillDir 'requirements.txt'
    if (Test-Path $reqFile) {
        Copy-Item -Force $reqFile $installedReqFile
    }

    # Install Python dependencies
    Write-Host "[INFO] Installing Python dependencies..." -ForegroundColor Yellow
    if (Test-Path $reqFile) {
        try {
            $pip = Invoke-External -Exe $python.Exe -Args @($python.Args + @('-m','pip','install','-q','-r',$reqFile)) -Quiet
            if ($pip.ExitCode -ne 0) {
                throw ($pip.Output -join "`n")
            }
        } catch {
            Write-Host "  [WARN] Could not auto-install Python packages." -ForegroundColor Yellow
            Write-Host "  Try: $($python.Exe) $($python.Args -join ' ') -m pip install -r `"$installedReqFile`"" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  [WARN] No requirements.txt found; skipping Python dependency install." -ForegroundColor Yellow
    }

    # Optional: Install Playwright browsers
    Write-Host "[INFO] Installing Playwright browsers (optional, for visual analysis)..." -ForegroundColor Yellow
    try {
        $pw = Invoke-External -Exe $python.Exe -Args @($python.Args + @('-m','playwright','install','chromium')) -Quiet
        if ($pw.ExitCode -ne 0) {
            throw ($pw.Output -join "`n")
        }
    } catch {
        Write-Host "  [WARN] Playwright install failed. Visual analysis will use WebFetch fallback." -ForegroundColor Yellow
    }
} catch {
    Write-Host ""
    Write-Host "[ERROR] Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    if ($keepTemp -and (Test-Path $TempDir)) {
        Write-Host "Temp dir kept at: $TempDir" -ForegroundColor Yellow
    }
    throw
} finally {
    if (-not $keepTemp -and (Test-Path $TempDir)) {
        Remove-Item -Recurse -Force $TempDir
    }
}

Write-Host ""
Write-Host "[OK] Codex SEO installed successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Usage:" -ForegroundColor Cyan
Write-Host "  1. Start Codex"
Write-Host "  2. Ask for SEO workflows (full audit, technical audit, schema validation)"
Write-Host ""
Write-Host "Python deps location: $installedReqFile" -ForegroundColor Gray
