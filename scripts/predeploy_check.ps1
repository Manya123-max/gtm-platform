<#
.SYNOPSIS
    Pre-deployment validation script for GTM Platform on Windows.
.DESCRIPTION
    Runs all dependency, Dockerfile, Python compilation, test suite, and frontend build validations.
    Exits with code 0 on SUCCESS, 1 on FAILURE.
#>

$ErrorActionPreference = "Continue"

Write-Host "`n======================================================================" -ForegroundColor Cyan
Write-Host "   GTM PLATFORM PRE-DEPLOYMENT VALIDATION (WINDOWS POWERSHELL)" -ForegroundColor Cyan
Write-Host "======================================================================`n" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

# Check Python availability
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "❌ Error: Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

# Run the unified Python validation suite
$pyScript = Join-Path $scriptDir "predeploy_check.py"
& python $pyScript
$pyExitCode = $LASTEXITCODE

if ($pyExitCode -ne 0) {
    Write-Host "`n[FAIL] Pre-deployment validation failed with exit code $pyExitCode" -ForegroundColor Red
    exit $pyExitCode
} else {
    Write-Host "`n[OK] Pre-deployment validation completed successfully!" -ForegroundColor Green
    exit 0
}
