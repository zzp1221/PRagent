#requires -version 5.1
<#
.SYNOPSIS
    Bring up a trycloudflare quick tunnel for PRAgent and wire it into .env.

.DESCRIPTION
    Starts the allow-list gateway (tunnel-gateway.js) and points cloudflared at
    it, so the public hostname only serves /webhooks/github and /health. The new
    hostname is written to .env as PRAGENT_PUBLIC_BASE_URL and the container is
    recreated so the app picks it up.

    Quick tunnels get a fresh random hostname on every start. For a stable name
    use tunnel.ps1, which needs a Cloudflare-managed domain plus a one-time
    "cloudflared tunnel login".

.PARAMETER Stop
    Stop the gateway and the tunnel started by this script.

.PARAMETER ExposeAdmin
    Serve the whole dashboard publicly instead of just the allow-listed paths.

.PARAMETER SkipCompose
    Update .env but do not recreate the container.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tunnel-quick.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tunnel-quick.ps1 -Stop
#>
[CmdletBinding()]
param(
    [string]$CloudflaredPath = "D:\cloudflared\cloudflared.exe",
    [int]$LocalPort = 0,
    [int]$GatewayPort = 8081,
    [switch]$ExposeAdmin,
    [switch]$SkipCompose,
    [string]$SyncWebhook = "",
    [switch]$Stop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$nl = [string][char]10
$stateDir = Join-Path $PSScriptRoot ".tunnel"
$gwPidFile = Join-Path $stateDir "gateway.pid"
$cfPidFile = Join-Path $stateDir "cloudflared.pid"
$cfLog = Join-Path $stateDir "cloudflared.log"
$cfErr = Join-Path $stateDir "cloudflared.err.log"
$gwLog = Join-Path $stateDir "gateway.log"
$gwErr = Join-Path $stateDir "gateway.err.log"
$envPath = Join-Path $PSScriptRoot ".env"
$gatewayJs = Join-Path $PSScriptRoot "tunnel-gateway.js"

function Stop-Tracked {
    foreach ($file in @($gwPidFile, $cfPidFile)) {
        if (Test-Path -LiteralPath $file) {
            $tracked = (Get-Content -LiteralPath $file -Raw).Trim()
            if ($tracked) {
                $proc = Get-Process -Id $tracked -ErrorAction SilentlyContinue
                # Pids are recycled across reboots: never touch a process that is
                # not ours, or a stale pid file could kill something unrelated.
                if ($proc -and $proc.ProcessName -in @("node", "cloudflared")) {
                    Write-Host "Stopping $($proc.ProcessName) (pid $($proc.Id))"
                    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
        }
    }
    # A leftover quick tunnel from an earlier run would keep a stale hostname alive.
    Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "Stopping stray cloudflared (pid $($_.Id))"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}

if ($Stop) {
    Stop-Tracked
    Write-Host "Tunnel stopped."
    return
}

if (-not (Test-Path -LiteralPath $CloudflaredPath)) { throw "cloudflared not found: $CloudflaredPath" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "node is required for the gateway but was not found on PATH." }

# Resolve the local port from .env when it is not given explicitly.
if ($LocalPort -le 0) {
    $LocalPort = 8080
    if (Test-Path -LiteralPath $envPath) {
        $portLine = [System.IO.File]::ReadAllLines($envPath) | Where-Object { $_ -match "^\s*PRAGENT_HTTP_PORT\s*=" } | Select-Object -First 1
        if ($portLine) { $LocalPort = [int]($portLine.Split("=", 2)[1].Trim()) }
    }
}

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

Write-Host "Checking http://127.0.0.1:$($LocalPort)/health ..."
$healthy = $false
foreach ($attempt in 1..3) {
    try {
        $probe = Invoke-WebRequest -Uri "http://127.0.0.1:$($LocalPort)/health" -UseBasicParsing -TimeoutSec 10
        if ($probe.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $healthy) { throw "PRAgent is not healthy on port $($LocalPort). Start it first (docker compose up -d)." }

Stop-Tracked

Write-Host "Starting gateway :$($GatewayPort) -> :$($LocalPort) ..."
$env:TUNNEL_LISTEN_PORT = "$GatewayPort"
$env:TUNNEL_UPSTREAM_PORT = "$LocalPort"
if ($ExposeAdmin) { $env:TUNNEL_EXPOSE_ADMIN = "1" } else { Remove-Item Env:TUNNEL_EXPOSE_ADMIN -ErrorAction SilentlyContinue }
$gwArgs = @{
    FilePath = (Get-Command node).Source
    ArgumentList = @([string]([char]34 + $gatewayJs + [char]34))
    WorkingDirectory = $PSScriptRoot
    RedirectStandardOutput = $gwLog
    RedirectStandardError = $gwErr
    WindowStyle = "Hidden"
    PassThru = $true
}
$gw = Start-Process @gwArgs
Set-Content -LiteralPath $gwPidFile -Value $gw.Id -NoNewline

$gatewayUp = $false
foreach ($attempt in 1..20) {
    Start-Sleep -Milliseconds 400
    try {
        $probe = Invoke-WebRequest -Uri "http://127.0.0.1:$($GatewayPort)/health" -UseBasicParsing -TimeoutSec 3
        if ($probe.StatusCode -eq 200) { $gatewayUp = $true; break }
    } catch { }
}
if (-not $gatewayUp) { throw "Gateway did not come up on port $($GatewayPort). See $gwLog" }
Write-Host "Gateway healthy on http://127.0.0.1:$($GatewayPort)/health"

Write-Host "Starting quick tunnel ..."
Remove-Item -LiteralPath $cfLog, $cfErr -Force -ErrorAction SilentlyContinue
$cfArgs = @{
    FilePath = $CloudflaredPath
    ArgumentList = @("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$($GatewayPort)")
    RedirectStandardOutput = $cfLog
    RedirectStandardError = $cfErr
    WindowStyle = "Hidden"
    PassThru = $true
}
$cf = Start-Process @cfArgs
Set-Content -LiteralPath $cfPidFile -Value $cf.Id -NoNewline

$publicUrl = ""
foreach ($attempt in 1..60) {
    Start-Sleep -Milliseconds 500
    foreach ($file in @($cfErr, $cfLog)) {
        if (-not (Test-Path -LiteralPath $file)) { continue }
        $found = Select-String -LiteralPath $file -Pattern "https://[a-z0-9][a-z0-9-]*[.]trycloudflare[.]com" -AllMatches | Select-Object -First 1
        if ($found) { $publicUrl = $found.Matches[0].Value; break }
    }
    if ($publicUrl) { break }
    if ($cf.HasExited) { break }
}
if (-not $publicUrl) { throw "Could not read the tunnel hostname. See $cfErr" }
Write-Host "Tunnel hostname  : $publicUrl"

# Wait until the edge actually serves traffic before advertising the URL.
$live = $false
foreach ($attempt in 1..30) {
    try {
        $probe = Invoke-WebRequest -Uri "$publicUrl/health" -UseBasicParsing -TimeoutSec 10
        if ($probe.StatusCode -eq 200) { $live = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if ($live) { Write-Host "Public health    : 200 OK" } else { Write-Warning "Tunnel is registered but /health is not answering publicly yet." }

$encoding = New-Object System.Text.UTF8Encoding($false)
if (Test-Path -LiteralPath $envPath) {
    $content = [System.IO.File]::ReadAllText($envPath)
    if ($content -match "(?m)^PRAGENT_PUBLIC_BASE_URL=.*$") {
        $content = [System.Text.RegularExpressions.Regex]::Replace($content, "(?m)^PRAGENT_PUBLIC_BASE_URL=.*$", "PRAGENT_PUBLIC_BASE_URL=$publicUrl")
    } else {
        $content = $content.TrimEnd([char]10, [char]13) + $nl + $nl + "PRAGENT_PUBLIC_BASE_URL=$publicUrl" + $nl
    }
    [System.IO.File]::WriteAllText($envPath, $content, $encoding)
    Write-Host "Updated PRAGENT_PUBLIC_BASE_URL in .env"
}

if (-not $SkipCompose -and (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Recreating the container so the new public URL takes effect ..."
    # A stale PRAGENT_PUBLIC_BASE_URL in the shell wins over .env during compose
    # interpolation, so pin it here instead of trusting the file alone.
    $env:PRAGENT_PUBLIC_BASE_URL = $publicUrl
    # docker writes its progress to stderr, which PowerShell would turn into a
    # terminating error; discard it and judge success by the exit code alone.
    & docker compose up -d --force-recreate --no-deps pragent 2>$null | Select-Object -Last 3
    $composeExit = $LASTEXITCODE
    if ($composeExit -ne 0) { Write-Warning "docker compose up -d exited with code $composeExit" }
    foreach ($attempt in 1..30) {
        Start-Sleep -Seconds 2
        try {
            $h = Invoke-WebRequest -Uri "http://127.0.0.1:$($LocalPort)/health" -UseBasicParsing -TimeoutSec 5
            if ($h.StatusCode -eq 200) { break }
        } catch { }
    }
}

$webhookUrl = "$publicUrl/webhooks/github"
$secret = ""
if (Test-Path -LiteralPath $envPath) {
    $secretLine = [System.IO.File]::ReadAllLines($envPath) | Where-Object { $_ -match "^\s*PRAGENT_GITHUB_WEBHOOK_SECRET\s*=" } | Select-Object -First 1
    if ($secretLine) { $secret = $secretLine.Split("=", 2)[1].Trim() }
}

# A quick tunnel gets a fresh hostname every run, so keep the GitHub hook in
# sync when the caller names a repository instead of editing it by hand.
if ($SyncWebhook) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Warning "gh CLI not found; update the webhook for $SyncWebhook by hand."
    } else {
        $hooks = & gh api "repos/$SyncWebhook/hooks" 2>$null | Out-String | ConvertFrom-Json
        $synced = 0
        foreach ($hook in $hooks) {
            if ([string]$hook.config.url -notlike "*trycloudflare.com*") { continue }
            $config = @{ url = $webhookUrl; content_type = "json" }
            if ($secret) { $config["secret"] = $secret }
            $body = @{ config = $config } | ConvertTo-Json -Compress
            $body | & gh api -X PATCH "repos/$SyncWebhook/hooks/$($hook.id)" --input - 2>$null | Out-Null
            Write-Host "Updated GitHub webhook $($hook.id) on $SyncWebhook"
            $synced++
        }
        if ($synced -eq 0) { Write-Host "No trycloudflare webhook found on $SyncWebhook; nothing to update." }
    }
}

Write-Host ""
Write-Host "Quick tunnel is live (hostname changes on every restart)."
Write-Host "  Payload URL : $webhookUrl"
Write-Host "  Content type: application/json"
Write-Host "  Secret      : $(if ($secret) { $secret } else { "(not set in .env)" })"
Write-Host "  Events      : Pull requests only"
Write-Host "  Health      : $publicUrl/health"
Write-Host "  Admin       : $(if ($ExposeAdmin) { "$publicUrl/ (public)" } else { "local only (http://127.0.0.1:$($LocalPort))" })"
Write-Host "  Access log  : $(Join-Path $PSScriptRoot "tunnel-access.log")"
Write-Host "  Stop        : powershell -ExecutionPolicy Bypass -File tunnel-quick.ps1 -Stop"
