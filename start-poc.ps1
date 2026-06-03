# start-poc.ps1
# Start de test API server (eigen venster, zichtbare logs) + cloudflared tunnel,
# leest de publieke URL uit en schrijft die naar ../.env (TEST_API_PUBLIC_URL).
#
# Draaien:
#   powershell -ExecutionPolicy Bypass -File .\start-poc.ps1

$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$env = Join-Path (Split-Path $dir -Parent) ".env"
$exe = Join-Path $dir "cloudflared.exe"
$py  = Join-Path $dir "test_api_server.py"
$log = Join-Path $dir "cloudflared.log"

Write-Host "`n=== NxtGn POC starten ===" -ForegroundColor Cyan

# 1) Bestaande processen op poort 8082 + oude cloudflared opruimen
$listen = Get-NetTCPConnection -LocalPort 8082 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    $listen.OwningProcess | Select-Object -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Oude server op poort 8082 gestopt." -ForegroundColor DarkGray
}
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 2) cloudflared aanwezig? Anders downloaden (geen admin nodig)
if (-not (Test-Path $exe)) {
    Write-Host "cloudflared.exe niet gevonden - downloaden..." -ForegroundColor Yellow
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $exe
}

# 3) API-server starten in een eigen, zichtbaar venster (zodat je de logs ziet)
Write-Host "API-server starten (eigen venster)..." -ForegroundColor Green
Start-Process -FilePath "python" -ArgumentList "-u `"$py`"" -WorkingDirectory $dir -WindowStyle Normal | Out-Null
Start-Sleep -Seconds 2

# 4) Tunnel starten (verborgen, log naar bestand) en URL uitlezen
Write-Host "Tunnel starten..." -ForegroundColor Green
Remove-Item $log -Force -ErrorAction SilentlyContinue
$p = Start-Process -FilePath $exe -ArgumentList @("tunnel","--url","http://127.0.0.1:8082","--no-autoupdate") `
        -RedirectStandardError $log -RedirectStandardOutput (Join-Path $dir "cloudflared.out") `
        -PassThru -WindowStyle Hidden
$p.Id | Out-File (Join-Path $dir "cloudflared.pid") -Encoding ascii

$url = $null
for ($i = 0; $i -lt 25; $i++) {
    Start-Sleep -Milliseconds 1000
    $content = Get-Content $log -Raw -ErrorAction SilentlyContinue
    $m = [regex]::Match([string]$content, "https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    if ($m.Success) { $url = $m.Value; break }
}

if (-not $url) {
    Write-Host "`nKon de tunnel-URL niet vinden. Check $log" -ForegroundColor Red
    exit 1
}

# 5) URL in .env zetten
if (Test-Path $env) {
    $lines = Get-Content $env
    if ($lines -match '^TEST_API_PUBLIC_URL=') {
        $lines = $lines -replace '^TEST_API_PUBLIC_URL=.*', "TEST_API_PUBLIC_URL=$url"
    } else {
        $lines += "TEST_API_PUBLIC_URL=$url"
    }
    $lines | Set-Content $env -Encoding utf8
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " POC draait!" -ForegroundColor Green
Write-Host " Publieke URL : $url" -ForegroundColor White
Write-Host " (ook opgeslagen in .env)" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " >> Zet deze URL in HALO context 'test_api_url' (Studio)," -ForegroundColor Yellow
Write-Host "    of vraag Claude om het via MCP bij te werken." -ForegroundColor Yellow
Write-Host ""
Write-Host " Stoppen: .\stop-poc.ps1" -ForegroundColor DarkGray
Write-Host ""
