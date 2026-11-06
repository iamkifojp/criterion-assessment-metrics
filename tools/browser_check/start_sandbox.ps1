# Start CAM from a sandbox copy for the Phase 4 browser checks (Windows).
#
#   powershell -ExecutionPolicy Bypass -File tools\browser_check\start_sandbox.ps1
#
# Copies only tracked files (no prefs, credentials, tokens or backups) into a
# temp sandbox, makes a venv there with exactly the bundle's pinned libraries,
# points every data path into the sandbox, and starts CAM on port 8611.
# Real data can't be reached: CAM_DB_PATH overrides the prefs, and the sandbox
# prefs name only the sandbox data folder. See README.md here.

param(
    [string]$Sandbox = (Join-Path $env:TEMP "cam-browser-sb"),
    [string]$Python = "py -3.14"
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
foreach ($d in "repo", "data", "home", "cam2data", "docs", "docs2") {
    New-Item -ItemType Directory -Force (Join-Path $Sandbox $d) | Out-Null
}
$SbRepo = Join-Path $Sandbox "repo"
$Data = Join-Path $Sandbox "data"

# 1. Tracked and unignored files only, refreshed on every start.
Push-Location $Repo
$files = git -c core.quotepath=off ls-files -co --exclude-standard
foreach ($f in $files) {
    $dst = Join-Path $SbRepo $f
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item -LiteralPath $f -Destination $dst -Force
}
Pop-Location

# 2. Refuse anything personal in the copy.
$bad = Get-ChildItem -Recurse -File $SbRepo | Where-Object {
    $_.Name -in @("credentials.json", "token.json") -or
    $_.Name -like "client_secret_*.json" -or $_.Name -like "*.bak-*"
}
if ($bad) { throw "REFUSING: personal or backup files in the sandbox copy: $($bad.FullName)" }

# 3. The venv with the bundle's exact libraries (made once).
$Venv = Join-Path $Sandbox "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Invoke-Expression "$Python -m venv `"$Venv`""
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    & $Py -m pip install --quiet --disable-pip-version-check --no-deps `
        -r (Join-Path $Repo "tools\bundle-requirements-windows.txt")
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $Venv    # so the next start retries
        throw "pip install of the pinned libraries failed"
    }
}

# 4. Sandbox prefs: the data folder is the sandbox's, so Sync runs as on a
#    teacher's computer. Refuse prefs that name anything outside.
$Prefs = Join-Path $SbRepo "local_device_prefs.json"
if (Test-Path $Prefs) {
    $p = Get-Content $Prefs -Raw | ConvertFrom-Json
    if ($p.db_custom_path -and -not $p.db_custom_path.StartsWith($Sandbox)) {
        throw "REFUSING: sandbox prefs point outside the sandbox: $($p.db_custom_path)"
    }
} else {
    # No BOM: Windows PowerShell 5.1's "-Encoding UTF8" adds one, and CAM's
    # json.load(encoding="utf-8") then rejects the file and drops these prefs.
    $json = @{ db_custom_path = $Data; setup_done = $true } | ConvertTo-Json
    [IO.File]::WriteAllText($Prefs, $json, (New-Object Text.UTF8Encoding $false))
}
if (-not (Test-Path (Join-Path $Data "acm_database.json"))) {
    Copy-Item (Join-Path $SbRepo "acm_database.json") $Data    # the fictional sample
}

# 5. Every data path into the sandbox; no OneDrive; browser opens are logged.
foreach ($v in "OneDrive", "OneDriveConsumer", "OneDriveCommercial") {
    Remove-Item "Env:$v" -ErrorAction SilentlyContinue
}
$env:CAM_DB_PATH = Join-Path $Data "acm_database.json"
$env:CAM2_APP_DATA = Join-Path $Sandbox "cam2data"
$env:CAM2_DOCUMENTS_OVERRIDE = Join-Path $Sandbox "docs2"
$env:CAM_DOCUMENTS_OVERRIDE = Join-Path $Sandbox "docs"
$env:HOME = Join-Path $Sandbox "home"
$env:USERPROFILE = Join-Path $Sandbox "home"
$env:CAM_SANDBOX_URL_LOG = Join-Path $Sandbox "opened-urls.txt"
# webbrowser splits BROWSER like a shell, so use forward slashes and quotes.
$fwd = { param($s) $s -replace "\\", "/" }
$env:BROWSER = "`"$(& $fwd $Py)`" `"$(& $fwd (Join-Path $SbRepo 'tools\browser_check\log_url.py'))`" %s"

Write-Host "sandbox DB: $env:CAM_DB_PATH"
Set-Location $SbRepo
& $Py -m streamlit run app.py --server.headless true --server.port 8611 --browser.gatherUsageStats false
