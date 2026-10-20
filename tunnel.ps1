#requires -version 5.1
<#
.SYNOPSIS
    Provision a stable, named Cloudflare Tunnel for PRAgent.

.DESCRIPTION
    Replaces the random trycloudflare.com quick tunnel with a named tunnel bound
    to a hostname you control. The tunnel only publishes /webhooks/github and
    /health so the admin console never reaches the public internet.

    Prerequisites:
      1. A Cloudflare account with the domain already added (DNS managed by CF).
      2. cloudflared installed (auto-detected, or pass -CloudflaredPath).
      3. A one-time interactive login: cloudflared tunnel login
         This writes the origin certificate to ~/.cloudflared/cert.pem.

.PARAMETER Hostname
    Public hostname for the webhook endpoint, e.g. agent.example.com.

.PARAMETER TunnelName
    Cloudflare tunnel name. Defaults to pragent.

.PARAMETER ExposeAdmin
    Publish the whole dashboard instead of only /webhooks/github and /health.
    Only do this together with a strong admin password.

.PARAMETER InstallService
    Register cloudflared as an auto-start Windows service. Requires an
    elevated shell. Without it the script falls back to a per-user scheduled task.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tunnel.ps1 -Hostname agent.example.com

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tunnel.ps1 -Hostname agent.example.com -InstallService
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Hostname,
    [string]$TunnelName = "pragent",
    [string]$LocalService = "http://127.0.0.1:8080",
    [string]$CloudflaredPath = "",
    [switch]$ExposeAdmin,
    [switch]$InstallService
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$cloudflaredHome = Join-Path $env:USERPROFILE ".cloudflared"
$configPath = Join-Path $cloudflaredHome "config.yml"

function Resolve-Cloudflared {
    param([string]$Explicit)
    if ($Explicit) {
        if (-not (Test-Path -LiteralPath $Explicit)) { throw "cloudflared not found at $Explicit" }
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($candidate in @("D:\cloudflared\cloudflared.exe", "$env:ProgramFiles\cloudflared\cloudflared.exe")) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "cloudflared.exe not found. Pass -CloudflaredPath or add it to PATH."
}

$exe = Resolve-Cloudflared -Explicit $CloudflaredPath

if ($Hostname -notmatch '^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$') {
    throw "Hostname must be a fully qualified domain name, got: $Hostname"
}

New-Item -ItemType Directory -Force -Path $cloudflaredHome | Out-Null

Write-Host "Checking Cloudflare login state ..."
$certPath = Join-Path $cloudflaredHome "cert.pem"
$listJson = ""
if (Test-Path -LiteralPath $certPath) {
    $listJson = (& $exe tunnel list --output json 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { $listJson = "" }
}
if (-not $listJson) {
    throw @"
Not logged in to Cloudflare. Run this once in an interactive shell, finish the
browser authorization, then re-run this script:

    & '$exe' tunnel login
"@
}

$tunnels = @()
try { $tunnels = $listJson | ConvertFrom-Json } catch { $tunnels = @() }

$existing = $tunnels | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
if ($existing) {
    $tunnelId = $existing.id
    Write-Host "Reusing existing tunnel '$TunnelName' ($tunnelId)."
} else {
    Write-Host "Creating tunnel '$TunnelName' ..."
    $created = (& $exe tunnel create $TunnelName 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "tunnel create failed: $created" }
    if ($created -match '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})') {
        $tunnelId = $Matches[1]
    } else {
        $refreshed = (& $exe tunnel list --output json 2>&1) -join "`n"
        $tunnelId = ($refreshed | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1).id
    }
    if (-not $tunnelId) { throw "could not determine tunnel id. Output: $created" }
    Write-Host "Created tunnel $tunnelId"
}

$credentials = Join-Path $cloudflaredHome "$tunnelId.json"
if (-not (Test-Path -LiteralPath $credentials)) {
    throw "Credentials file missing: $credentials (re-create the tunnel)."
}

Write-Host "Routing DNS $Hostname -> $TunnelName ..."
$routeOut = (& $exe tunnel route dns $TunnelName $Hostname 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) {
    if ($routeOut -match 'already exists|already configured') {
        Write-Host "DNS record already points at this tunnel; continuing."
    } else {
        throw "tunnel route dns failed: $routeOut"
    }
}

$ingress = @()
if ($ExposeAdmin) {
    $ingress += "  - hostname: $Hostname"
    $ingress += "    service: $LocalService"
} else {
    $ingress += "  - hostname: $Hostname"
    $ingress += "    path: ^/webhooks/github$"
    $ingress += "    service: $LocalService"
    $ingress += "  - hostname: $Hostname"
    $ingress += "    path: ^/health$"
    $ingress += "    service: $LocalService"
}
$ingress += "  - service: http_status:404"

$yaml = @(
    "# Generated by tunnel.ps1. Tunnel: $TunnelName ($tunnelId)",
    "tunnel: $tunnelId",
    "credentials-file: $($credentials -replace '\\', '/')",
    "",
    "ingress:"
) + $ingress

$encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, ($yaml -join "`n") + "`n", $encoding)
Write-Host "Wrote $configPath"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if ($InstallService) {
    if (-not $isAdmin) {
        throw "InstallService requires an elevated shell. Re-run as Administrator, or omit -InstallService."
    }
    & $exe service uninstall *> $null
    & $exe --config $configPath service install 2>&1 | Select-Object -Last 3
    Start-Service cloudflared
    Write-Host "Installed and started the cloudflared Windows service."
} else {
    $taskName = "PRAgentCloudflared"
    $action = New-ScheduledTaskAction -Execute $exe -Argument "tunnel --config `"$configPath`" run $TunnelName"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
    try {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        Start-ScheduledTask -TaskName $taskName
        Write-Host "Registered scheduled task '$taskName' (auto-restart on failure)."
        Write-Host "Note: add -InstallService from an elevated shell for a native service instead."
    } catch {
        Write-Warning "Could not register the scheduled task: $($_.Exception.Message)"
        Write-Host "Run the tunnel manually: & '$exe' tunnel --config '$configPath' run $TunnelName"
    }
}

$publicUrl = "https://$Hostname"
$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path -LiteralPath $envPath) {
    $content = [System.IO.File]::ReadAllText($envPath)
    if ($content -match '(?m)^PRAGENT_PUBLIC_BASE_URL=.*$') {
        $content = [System.Text.RegularExpressions.Regex]::Replace(
            $content, '(?m)^PRAGENT_PUBLIC_BASE_URL=.*$', "PRAGENT_PUBLIC_BASE_URL=$publicUrl")
    } else {
        $content = $content.TrimEnd("`n") + "`n`nPRAGENT_PUBLIC_BASE_URL=$publicUrl`n"
    }
    [System.IO.File]::WriteAllText($envPath, $content, $encoding)
    Write-Host "Updated PRAGENT_PUBLIC_BASE_URL=$publicUrl in .env"
} else {
    Write-Warning ".env not found; set PRAGENT_PUBLIC_BASE_URL=$publicUrl manually."
}

$compose = Get-Command docker -ErrorAction SilentlyContinue
if ($compose) {
    Write-Host "Recreating the container so the new public URL takes effect ..."
    & docker compose up -d 2>&1 | Select-Object -Last 3
}

Write-Host "Waiting for $publicUrl/health ..."
$ready = $false
foreach ($attempt in 1..30) {
    try {
        $response = Invoke-WebRequest -Uri "$publicUrl/health" -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        Start-Sleep -Seconds 3
    }
}

if (-not $ready) {
    Write-Warning "DNS or tunnel is not serving yet. Verify the hostname is managed by Cloudflare, then retry."
} else {
    Write-Host ""
    Write-Host "Stable tunnel is live."
    Write-Host "  Webhook URL : $publicUrl/webhooks/github"
    Write-Host "  Health      : $publicUrl/health"
    if (-not $ExposeAdmin) {
        Write-Host "  Admin       : local only (http://127.0.0.1:8080)"
    }
}
