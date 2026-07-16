param(
    [string]$EnvFile = (Join-Path $PSScriptRoot "..\pseudoprod\.env")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$envPath = (Resolve-Path $EnvFile).Path
$waitress = Join-Path $repoDir ".venv\Scripts\waitress-serve.exe"

if (-not (Test-Path -LiteralPath $waitress)) {
    throw "Waitress is not installed in the project virtual environment."
}

$env:DJANGO_ENV_FILE = $envPath
Push-Location (Join-Path $repoDir "backend")
try {
    & $waitress --listen=0.0.0.0:8080 config.wsgi:application
}
finally {
    Pop-Location
}
