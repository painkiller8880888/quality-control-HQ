param(
    [string]$ServiceName = "QualityControlHQ-Pseudoprod"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$repoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtimeEnv = Join-Path $repoDir "deployment\pseudoprod\.env"
$publicUrlLine = Get-Content -LiteralPath $runtimeEnv | Where-Object {
    $_ -match '^APP_PUBLIC_URL='
} | Select-Object -Last 1
if (-not $publicUrlLine) { throw "APP_PUBLIC_URL was not found." }
$publicUrl = ($publicUrlLine -split '=', 2)[1].Trim()

$listenerLine = netstat.exe -ano -p tcp | Select-String ':8080\s+.*LISTENING' | Select-Object -First 1
if (-not $listenerLine -or $listenerLine.Line -notmatch '\s+(\d+)\s*$') {
    throw "Waitress is not listening on TCP 8080."
}
$oldListenerPid = [int]$matches[1]
$service = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'"
if (-not $service -or -not $service.ProcessId) {
    throw "The WinSW service process was not found."
}

$ancestorPid = $oldListenerPid
$belongsToService = $false
for ($depth = 0; $depth -lt 10 -and $ancestorPid; $depth++) {
    if ($ancestorPid -eq [int]$service.ProcessId) {
        $belongsToService = $true
        break
    }
    $ancestor = Get-CimInstance Win32_Process -Filter "ProcessId=$ancestorPid"
    if (-not $ancestor) { break }
    $ancestorPid = [int]$ancestor.ParentProcessId
}
if (-not $belongsToService) {
    throw "Refusing to stop a TCP 8080 listener that is not a child of $ServiceName."
}

$startedAt = Get-Date
Stop-Process -Id $oldListenerPid -Force

$deadline = (Get-Date).AddSeconds(45)
$newListenerPid = $null
do {
    Start-Sleep -Seconds 2
    $candidate = netstat.exe -ano -p tcp | Select-String ':8080\s+.*LISTENING' | Select-Object -First 1
    if ($candidate -and $candidate.Line -match '\s+(\d+)\s*$') {
        $candidatePid = [int]$matches[1]
        if ($candidatePid -ne $oldListenerPid) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing $publicUrl -TimeoutSec 5
                if ($response.StatusCode -eq 200) { $newListenerPid = $candidatePid }
            }
            catch {}
        }
    }
} while (-not $newListenerPid -and (Get-Date) -lt $deadline)

if (-not $newListenerPid) {
    throw "WinSW did not restore Waitress within 45 seconds."
}

[pscustomobject]@{
    Service = (Get-Service -Name $ServiceName).Status
    OldListenerPid = $oldListenerPid
    NewListenerPid = $newListenerPid
    RecoverySeconds = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    HttpStatus = 200
}
