param(
    [string]$ServiceName = "QualityControlHQ-Worker-Pseudoprod",
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $PrepareOnly -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$repoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$serviceDir = Join-Path $PSScriptRoot "service"
$webWrapper = Join-Path $serviceDir "QualityControlHQ-Pseudoprod.exe"
$wrapper = Join-Path $serviceDir "QualityControlHQ-Worker-Pseudoprod.exe"
$config = Join-Path $serviceDir "QualityControlHQ-Worker-Pseudoprod.xml"
$runtimeEnv = Join-Path $repoDir "deployment\pseudoprod\.env"
$python = Join-Path $repoDir ".venv\Scripts\python.exe"
$expectedHash = "05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA"

foreach ($requiredPath in @($webWrapper, $runtimeEnv, $python)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file was not found: $requiredPath"
    }
}

$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $webWrapper).Hash
if ($actualHash -ne $expectedHash) {
    throw "WinSW SHA256 verification failed."
}
if (-not (Test-Path -LiteralPath $wrapper)) {
    Copy-Item -LiteralPath $webWrapper -Destination $wrapper
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $wrapper).Hash -ne $expectedHash) {
    throw "Worker WinSW SHA256 verification failed."
}

$xml = @"
<service>
  <id>$ServiceName</id>
  <name>Quality Control HQ Worker Pseudoprod</name>
  <description>Persistent PostgreSQL-backed Quality Control HQ job worker.</description>
  <executable>$python</executable>
  <arguments>manage.py run_job_worker --poll-seconds 2</arguments>
  <workingdirectory>$(Join-Path $repoDir 'backend')</workingdirectory>
  <env name="DJANGO_ENV_FILE" value="$runtimeEnv" />
  <depend>postgresql-x64-18</depend>
  <startmode>Automatic</startmode>
  <stoptimeout>30 sec</stoptimeout>
  <onfailure action="restart" delay="10 sec" />
  <onfailure action="restart" delay="30 sec" />
  <resetfailure>1 hour</resetfailure>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>8</keepFiles>
  </log>
</service>
"@
[System.IO.File]::WriteAllText(
    $config,
    $xml,
    (New-Object System.Text.UTF8Encoding($false))
)

if ($PrepareOnly) {
    Write-Output "Worker service files prepared: $wrapper"
    return
}

$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $existingService) {
    & $wrapper install
    if ($LASTEXITCODE -ne 0) { throw "Worker WinSW service installation failed." }
}

& $wrapper start
if ($LASTEXITCODE -ne 0) { throw "Worker WinSW service start failed." }
(Get-Service -Name $ServiceName).WaitForStatus("Running", (New-TimeSpan -Seconds 60))

Get-Service -Name $ServiceName | Select-Object Name, Status, StartType
