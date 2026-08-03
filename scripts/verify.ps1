[CmdletBinding()]
param(
    [ValidateSet("Backend", "Frontend", "All")]
    [string]$Scope = "All"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    Write-Host ("> {0} {1}" -f $Command, ($Arguments -join " "))
    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $Command @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw ("Command failed with exit code {0}: {1}" -f $LASTEXITCODE, $Command)
        }
    }
    finally {
        Pop-Location
    }
}

if ($Scope -in @("Backend", "All")) {
    Invoke-Checked -Command "python" -Arguments @("backend/manage.py", "check") -WorkingDirectory $repoRoot
    Invoke-Checked -Command "python" -Arguments @("backend/manage.py", "makemigrations", "--check", "--dry-run") -WorkingDirectory $repoRoot
    Invoke-Checked -Command "python" -Arguments @("backend/manage.py", "test", "config", "quality", "--verbosity", "2") -WorkingDirectory $repoRoot
}

if ($Scope -in @("Frontend", "All")) {
    $frontendRoot = Join-Path $repoRoot "frontend"
    Invoke-Checked -Command "npm" -Arguments @("run", "lint") -WorkingDirectory $frontendRoot
    Invoke-Checked -Command "npm" -Arguments @("run", "build") -WorkingDirectory $frontendRoot

    $distRoot = Join-Path $frontendRoot "dist"
    $builtFile = Get-ChildItem -LiteralPath $distRoot -File -Recurse | Select-Object -First 1
    if ($null -eq $builtFile) {
        throw "Frontend build output is empty: $distRoot"
    }
}
