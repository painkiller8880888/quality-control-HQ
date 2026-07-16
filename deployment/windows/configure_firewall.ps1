param(
    [Parameter(Mandatory = $true)]
    [string]$ClientIp,
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$parsedIp = $null
if (-not [System.Net.IPAddress]::TryParse($ClientIp, [ref]$parsedIp) -or
    $parsedIp.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "ClientIp must be one IPv4 address."
}

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$ruleName = "Quality Control HQ Pseudoprod HTTP"
$remoteAddress = "$ClientIp/32"
$enabledAllowRules = Get-NetFirewallRule -Direction Inbound -Action Allow -Enabled True
$repoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$waitressPrograms = @(
    (Join-Path $repoDir ".venv\Scripts\waitress-serve.exe"),
    (Join-Path $repoDir ".venv\Scripts\python.exe")
)
$postgresPrograms = @("C:\Program Files\PostgreSQL\18\bin\postgres.exe")

function Test-RuleAllowsPort {
    param(
        $Rule,
        [int]$TargetPort,
        [string[]]$TargetPrograms,
        [string[]]$TargetServices = @()
    )
    $portFilter = $Rule | Get-NetFirewallPortFilter
    if ($portFilter.Protocol -notin @("TCP", "Any")) { return $false }
    if ($portFilter.LocalPort -notcontains "$TargetPort" -and
        $portFilter.LocalPort -notcontains "Any") { return $false }

    if ($Rule.Owner) { return $false }
    $applicationFilter = $Rule | Get-NetFirewallApplicationFilter
    $serviceFilter = $Rule | Get-NetFirewallServiceFilter
    if ($applicationFilter.Package -and $applicationFilter.Package -ne "Any") {
        return $false
    }

    $program = [Environment]::ExpandEnvironmentVariables($applicationFilter.Program)
    if ($program -and $program -ne "Any") {
        return $TargetPrograms -contains $program
    }
    if ($serviceFilter.Service -and $serviceFilter.Service -ne "Any") {
        return $TargetServices -contains $serviceFilter.Service
    }
    return $true
}

$conflictingRules = foreach ($rule in $enabledAllowRules) {
    if ($rule.DisplayName -eq $ruleName) { continue }
    if (Test-RuleAllowsPort $rule $Port $waitressPrograms) { $rule }
}
if ($conflictingRules) {
    $names = ($conflictingRules.DisplayName | Sort-Object -Unique) -join ", "
    throw "Another enabled inbound allow rule can reach TCP ${Port}: $names"
}

$postgresRules = foreach ($rule in $enabledAllowRules) {
    if (Test-RuleAllowsPort $rule 5432 $postgresPrograms @("postgresql-x64-18")) { $rule }
}
if ($postgresRules) {
    $names = ($postgresRules.DisplayName | Sort-Object -Unique) -join ", "
    throw "An enabled inbound allow rule can reach PostgreSQL TCP 5432: $names"
}

$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue

if ($existingRule) {
    $existingRule | Set-NetFirewallRule -Enabled True -Profile Domain,Private -Action Allow
    $existingRule | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $remoteAddress
    $existingRule | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
}
else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Port `
        -RemoteAddress $remoteAddress `
        -Profile Domain,Private
}

Get-NetFirewallRule -DisplayName $ruleName |
    Get-NetFirewallAddressFilter |
    Select-Object Name, RemoteAddress
