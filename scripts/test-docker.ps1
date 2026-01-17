# PowerShell script to run tests in Docker
# Usage: .\scripts\test-docker.ps1 [options]

param(
    [switch]$Coverage = $false,
    [switch]$Exec = $false,
    [switch]$Help = $false
)

if ($Help) {
    Write-Host "Docker Test Runner for Tattoo Booking Bot" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Usage: .\scripts\test-docker.ps1 [options]" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Options:" -ForegroundColor Yellow
    Write-Host "  -Coverage         Generate coverage report"
    Write-Host "  -Exec             Run tests in running container (requires docker compose up)"
    Write-Host "  -Help             Show this help message"
    Write-Host ""
    Write-Host "Examples:" -ForegroundColor Yellow
    Write-Host "  .\scripts\test-docker.ps1              # Run tests in isolated container"
    Write-Host "  .\scripts\test-docker.ps1 -Coverage    # With coverage"
    Write-Host "  .\scripts\test-docker.ps1 -Exec        # In running container"
    exit 0
}

if ($Exec) {
    Write-Host "Running tests in running container..." -ForegroundColor Cyan
    docker compose exec api pytest tests/ -v
} else {
    if ($Coverage) {
        Write-Host "Running tests in Docker with coverage..." -ForegroundColor Cyan
        docker compose -f docker-compose.test.yml run --rm test pytest tests/ -v --cov=app --cov-report=term
    } else {
        Write-Host "Running tests in isolated Docker container..." -ForegroundColor Cyan
        docker compose -f docker-compose.test.yml run --rm test
    }
}
