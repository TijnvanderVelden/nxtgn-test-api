# stop-poc.ps1
# Stopt de test API server en de cloudflared tunnel.
#
# Draaien:
#   powershell -ExecutionPolicy Bypass -File .\stop-poc.ps1

$dir = $PSScriptRoot

# Tunnel stoppen (via opgeslagen PID + alle cloudflared processen)
$tpid = Get-Content (Join-Path $dir "cloudflared.pid") -ErrorAction SilentlyContinue
if ($tpid) { Stop-Process -Id $tpid -Force -ErrorAction SilentlyContinue }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# API-server stoppen (alles wat op 8082 luistert)
$listen = Get-NetTCPConnection -LocalPort 8082 -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    $listen.OwningProcess | Select-Object -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "POC gestopt (server + tunnel)." -ForegroundColor Green
