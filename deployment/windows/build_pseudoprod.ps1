param(
    [string]$RuntimeEnvFile = (Join-Path $PSScriptRoot "..\pseudoprod\.env"),
    [string]$MigrationEnvFile = (Join-Path $PSScriptRoot "..\pseudoprod\.env.migrate"),
    [string]$ServiceName = "QualityControlHQ-Pseudoprod",
    [string]$WorkerServiceName = "QualityControlHQ-Worker-Pseudoprod"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtimeEnvPath = (Resolve-Path $RuntimeEnvFile).Path
$migrationEnvPath = (Resolve-Path $MigrationEnvFile).Path
$python = Join-Path $repoDir ".venv\Scripts\python.exe"
$liveFrontend = Join-Path $repoDir "backend\frontend_dist"
$stagedFrontend = Join-Path $repoDir "runtime\staging\frontend_dist"
$rollbackFrontend = Join-Path $repoDir ("runtime\rollback\{0}\frontend_dist" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment was not found: $python"
}

$env:DJANGO_ENV_FILE = $runtimeEnvPath
& $python (Join-Path $repoDir "backend\manage.py") check --deploy
if ($LASTEXITCODE -ne 0) { throw "Django deployment check failed." }

Push-Location (Join-Path $repoDir "frontend")
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
    npm run build -- --base=/static/ --outDir=../runtime/staging/frontend_dist --emptyOutDir
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}
finally {
    Pop-Location
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$restartService = $service -and $service.Status -eq "Running"
$workerService = Get-Service -Name $WorkerServiceName -ErrorAction SilentlyContinue
$restartWorkerService = $workerService -and $workerService.Status -eq "Running"
$oldFrontendSaved = $false
$newFrontendInstalled = $false

if ($restartWorkerService) {
    Stop-Service -Name $WorkerServiceName -Force
    (Get-Service -Name $WorkerServiceName).WaitForStatus("Stopped", (New-TimeSpan -Seconds 30))
}
if ($restartService) {
    Stop-Service -Name $ServiceName -Force
    (Get-Service -Name $ServiceName).WaitForStatus("Stopped", (New-TimeSpan -Seconds 30))
}

try {
    $env:DJANGO_ENV_FILE = $migrationEnvPath
    & $python (Join-Path $repoDir "backend\manage.py") migrate --noinput
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }

    if (Test-Path -LiteralPath $liveFrontend) {
        New-Item -ItemType Directory -Path (Split-Path $rollbackFrontend) -Force | Out-Null
        Move-Item -LiteralPath $liveFrontend -Destination $rollbackFrontend
        $oldFrontendSaved = $true
    }
    Move-Item -LiteralPath $stagedFrontend -Destination $liveFrontend
    $newFrontendInstalled = $true

    $env:DJANGO_ENV_FILE = $runtimeEnvPath
    & $python (Join-Path $repoDir "backend\manage.py") collectstatic --noinput
    if ($LASTEXITCODE -ne 0) { throw "collectstatic failed." }

    & $python (Join-Path $repoDir "backend\manage.py") check --deploy
    if ($LASTEXITCODE -ne 0) { throw "Django deployment check failed." }

    if ($restartService) {
        Start-Service -Name $ServiceName
        (Get-Service -Name $ServiceName).WaitForStatus("Running", (New-TimeSpan -Seconds 30))
    }
    if ($restartWorkerService) {
        Start-Service -Name $WorkerServiceName
        (Get-Service -Name $WorkerServiceName).WaitForStatus("Running", (New-TimeSpan -Seconds 30))
    }
}
catch {
    if ($newFrontendInstalled -and (Test-Path -LiteralPath $liveFrontend)) {
        $resolvedLive = (Resolve-Path $liveFrontend).Path
        if (-not $resolvedLive.StartsWith($repoDir, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a frontend directory outside the repository."
        }
        Remove-Item -LiteralPath $resolvedLive -Recurse -Force
    }
    if ($oldFrontendSaved -and (Test-Path -LiteralPath $rollbackFrontend)) {
        Move-Item -LiteralPath $rollbackFrontend -Destination $liveFrontend
    }
    if ($restartService) {
        Start-Service -Name $ServiceName
    }
    if ($restartWorkerService) {
        Start-Service -Name $WorkerServiceName
    }
    throw
}
