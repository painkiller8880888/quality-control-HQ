param(
    [Parameter(Mandatory = $true)]
    [string]$PublicHost,
    [string]$ApprovalId = "IFC20260716-001",
    [string]$ApprovalExpires = "2027-07-16",
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sourceEnv = Join-Path $repoDir ".env"
$runtimeEnv = Join-Path $repoDir "deployment\pseudoprod\.env"
$migrationEnv = Join-Path $repoDir "deployment\pseudoprod\.env.migrate"
$bootstrapEnv = Join-Path $repoDir "deployment\postgresql\.env.bootstrap"
$python = Join-Path $repoDir ".venv\Scripts\python.exe"
$publicUrl = "http://${PublicHost}:${Port}"
$mediaRoot = (Join-Path $repoDir "runtime\pseudoprod\media").Replace('\', '/')
$staticRoot = (Join-Path $repoDir "runtime\pseudoprod\static").Replace('\', '/')

function Get-EnvValue {
    param([string]$Path, [string]$Name)
    $line = Get-Content -LiteralPath $Path | Where-Object {
        $_ -match "^\s*$([regex]::Escape($Name))\s*="
    } | Select-Object -Last 1
    if (-not $line) { throw "Missing $Name in $Path" }
    return ($line -split '=', 2)[1].Trim()
}

function New-Secret {
    param([int]$ByteCount = 48)
    $bytes = New-Object byte[] $ByteCount
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Write-PrivateEnv {
    param([string]$Path, [string]$Content)
    [System.IO.File]::WriteAllText(
        $Path,
        $Content.TrimStart() + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false))
    )
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $Path /inheritance:r /grant:r "${env:USERNAME}:(M)" "${currentIdentity}:(M)" "SYSTEM:(F)" "Administrators:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to protect $Path" }
}

if (-not (Test-Path -LiteralPath $sourceEnv)) { throw "Development .env was not found." }
if (-not (Test-Path -LiteralPath $python)) { throw "Project Python was not found." }
if ($PublicHost -notmatch '^[A-Za-z0-9.-]+$') { throw "PublicHost is invalid." }
try { [void][datetime]::ParseExact($ApprovalExpires, 'yyyy-MM-dd', $null) }
catch { throw "ApprovalExpires must use yyyy-MM-dd." }

$postgresPassword = Get-EnvValue $sourceEnv "POSTGRES_PASS"
$djangoSecret = New-Secret 64
$appPassword = New-Secret 48
$migrationPassword = New-Secret 48
$version = Get-Date -Format "yyyyMMdd-HHmmss"

New-Item -ItemType Directory -Path (Split-Path $runtimeEnv), (Split-Path $bootstrapEnv), $mediaRoot, $staticRoot -Force | Out-Null

Write-PrivateEnv $runtimeEnv @"
APP_ENV=pseudoprod
APP_VERSION=$version
APP_PUBLIC_HOST=$PublicHost
APP_PUBLIC_PORT=$Port
APP_PUBLIC_URL=$publicUrl
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=$djangoSecret
DJANGO_ALLOWED_HOSTS=$PublicHost,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=$publicUrl
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=quality_prodlike
DB_USER=quality_prodlike_app
DB_PASSWORD=$appPassword
MEDIA_ROOT=$mediaRoot
STATIC_ROOT=$staticRoot
SERVE_MEDIA_FILES=true
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
ALLOW_INSECURE_HTTP=true
HTTP_RISK_ACCEPTANCE_ID=$ApprovalId
HTTP_RISK_ACCEPTANCE_EXPIRES=$ApprovalExpires
"@

Write-PrivateEnv $migrationEnv @"
APP_ENV=pseudoprod
APP_VERSION=$version
APP_PUBLIC_URL=$publicUrl
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=$djangoSecret
DJANGO_ALLOWED_HOSTS=$PublicHost,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=$publicUrl
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=quality_prodlike
DB_USER=quality_prodlike_migrator
DB_PASSWORD=$migrationPassword
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
ALLOW_INSECURE_HTTP=true
HTTP_RISK_ACCEPTANCE_ID=$ApprovalId
HTTP_RISK_ACCEPTANCE_EXPIRES=$ApprovalExpires
"@

Write-PrivateEnv $bootstrapEnv @"
POSTGRES_ADMIN_USER=postgres
POSTGRES_ADMIN_PASSWORD=$postgresPassword
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
PSEUDOPROD_DB_NAME=quality_prodlike
PSEUDOPROD_DB_USER=quality_prodlike_app
PSEUDOPROD_DB_PASSWORD=$appPassword
PSEUDOPROD_MIGRATION_USER=quality_prodlike_migrator
PSEUDOPROD_MIGRATION_PASSWORD=$migrationPassword
"@

& $python (Join-Path $repoDir "deployment\postgresql\initialize_databases.py") --env-file $bootstrapEnv --pseudoprod-only
if ($LASTEXITCODE -ne 0) { throw "Database initialization failed." }

Write-Output "Pseudoproduction environment initialized for $publicUrl"
Write-Output "Runtime environment: $runtimeEnv"
Write-Output "Migration environment: $migrationEnv"
