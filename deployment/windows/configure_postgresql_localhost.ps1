param(
    [string]$ConfigPath = "C:\Program Files\PostgreSQL\18\data\postgresql.conf",
    [string]$ServiceName = "postgresql-x64-18"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$resolvedConfig = (Resolve-Path -LiteralPath $ConfigPath).Path
$dataDirectory = (Split-Path $resolvedConfig -Parent).TrimEnd('\')
$expectedDirectory = "C:\Program Files\PostgreSQL\18\data"
if (-not $dataDirectory.Equals($expectedDirectory, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to edit an unexpected PostgreSQL data directory: $dataDirectory"
}

$content = [System.IO.File]::ReadAllText($resolvedConfig)
$pattern = "(?m)^\s*listen_addresses\s*=\s*'[^']*'\s*(?:#.*)?$"
$matches = [regex]::Matches($content, $pattern)
if ($matches.Count -ne 1) {
    throw "Expected exactly one active listen_addresses setting."
}

$backupPath = "$resolvedConfig.$(Get-Date -Format 'yyyyMMdd-HHmmss').bak"
Copy-Item -LiteralPath $resolvedConfig -Destination $backupPath
$updated = [regex]::Replace($content, $pattern, "listen_addresses = 'localhost'")
[System.IO.File]::WriteAllText(
    $resolvedConfig,
    $updated,
    (New-Object System.Text.UTF8Encoding($false))
)

Restart-Service -Name $ServiceName -Force
(Get-Service -Name $ServiceName).WaitForStatus("Running", (New-TimeSpan -Seconds 60))

& (Join-Path $PSScriptRoot "verify_network.ps1")
Write-Output "Backup: $backupPath"
