param(
    [Parameter(Mandatory = $true)]
    [string]$LoginName,
    [string]$DisplayName = $LoginName
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$env:DJANGO_ENV_FILE = (Resolve-Path (Join-Path $repoDir "deployment\pseudoprod\.env")).Path
$python = Join-Path $repoDir ".venv\Scripts\python.exe"

& $python (Join-Path $repoDir "backend\manage.py") bootstrap_admin `
    --login-name $LoginName `
    --display-name $DisplayName
if ($LASTEXITCODE -ne 0) { throw "Admin creation failed." }
