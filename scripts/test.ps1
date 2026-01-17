# PowerShell script to run tests locally
# Usage: .\scripts\test.ps1 [options]

param(
    [string]$File = "",
    [string]$Pattern = "",
    [switch]$Coverage = $false,
    [switch]$Fast = $false,
    [switch]$Help = $false
)

if ($Help) {
    Write-Host "Test Runner for Tattoo Booking Bot" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage: .\scripts\test.ps1 [options]" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Options:" -ForegroundColor Yellow
    Write-Host "  -File <path>      Run specific test file (e.g., tests/test_webhooks.py)"
    Write-Host "  -Pattern <name>   Run tests matching pattern (e.g., whatsapp)"
    Write-Host "  -Coverage         Generate coverage report"
    Write-Host "  -Fast             Run tests in quiet mode"
    Write-Host "  -Help             Show this help message"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Yellow
    Write-Host "  .\scripts\test.ps1                    # Run all tests"
    Write-Host "  .\scripts\test.ps1 -File tests/test_webhooks.py"
    Write-Host "  .\scripts\test.ps1 -Pattern whatsapp"
    Write-Host "  .\scripts\test.ps1 -Coverage"
    exit 0
}

$pytestArgs = @()

if ($Fast) {
    $pytestArgs += "-q"
} else {
    $pytestArgs += "-v"
}

if ($File) {
    $pytestArgs += $File
} else {
    $pytestArgs += "tests/"
}

if ($Pattern) {
    $pytestArgs += "-k"
    $pytestArgs += $Pattern
}

if ($Coverage) {
    $pytestArgs += "--cov=app"
    $pytestArgs += "--cov-report=html"
    $pytestArgs += "--cov-report=term"
}

Write-Host "Running: pytest $($pytestArgs -join ' ')" -ForegroundColor Cyan
pytest $pytestArgs

if ($Coverage) {
    Write-Host "`nCoverage report generated in htmlcov/index.html" -ForegroundColor Green
}
