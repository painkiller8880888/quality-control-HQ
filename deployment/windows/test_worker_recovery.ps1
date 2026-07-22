param(
    [string]$ServiceName = "QualityControlHQ-Worker-Pseudoprod"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$service = Get-Service -Name $ServiceName -ErrorAction Stop
if ($service.Status -ne "Running") {
    throw "The worker service is not running."
}
$wrapperLog = Join-Path $PSScriptRoot "service\QualityControlHQ-Worker-Pseudoprod.wrapper.log"
$startedLine = Get-Content -LiteralPath $wrapperLog | Select-String 'Started process (\d+)' | Select-Object -Last 1
if (-not $startedLine -or $startedLine.Line -notmatch 'Started process (\d+)') {
    throw "The worker PID was not found in the WinSW log."
}
$oldPid = [int]$matches[1]
$oldProcess = Get-Process -Id $oldPid -ErrorAction Stop
if ($oldProcess.ProcessName -notmatch '^python') {
    throw "Refusing to stop a non-Python process."
}
$startedAt = Get-Date
Stop-Process -Id $oldPid -Force

$deadline = (Get-Date).AddSeconds(45)
$newPid = $null
do {
    Start-Sleep -Seconds 2
    $candidate = Get-Content -LiteralPath $wrapperLog | Select-String 'Started process (\d+)' | Select-Object -Last 1
    if ($candidate -and $candidate.Line -match 'Started process (\d+)') {
        $candidatePid = [int]$matches[1]
        if ($candidatePid -ne $oldPid -and (Get-Process -Id $candidatePid -ErrorAction SilentlyContinue)) {
            $newPid = $candidatePid
        }
    }
} while (-not $newPid -and (Get-Date) -lt $deadline)

if (-not $newPid) {
    throw "WinSW did not restore the worker within 45 seconds."
}

[pscustomobject]@{
    Service = (Get-Service -Name $ServiceName).Status
    OldWorkerPid = $oldPid
    NewWorkerPid = $newPid
    RecoverySeconds = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
}
