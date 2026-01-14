# Release script - bumps version, commits, tags, and pushes
# Usage: .\scripts\release.ps1 [patch|minor|major]

param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("patch", "minor", "major")]
    [string]$BumpType
)

$ErrorActionPreference = "Stop"
$VersionFile = "VERSION"

# Check if VERSION file exists
if (-not (Test-Path $VersionFile)) {
    Write-Host "Error: VERSION file not found" -ForegroundColor Red
    exit 1
}

# Get current version (remove BOM and whitespace)
$CurrentVersion = (Get-Content $VersionFile -Raw).Trim() -replace '^\uFEFF', ''
$VersionParts = $CurrentVersion -split '\.'
$Major = [int]$VersionParts[0]
$Minor = [int]$VersionParts[1]
$Patch = [int]$VersionParts[2]

# Bump version
switch ($BumpType) {
    "major" {
        $Major++
        $Minor = 0
        $Patch = 0
    }
    "minor" {
        $Minor++
        $Patch = 0
    }
    "patch" {
        $Patch++
    }
}

$NewVersion = "$Major.$Minor.$Patch"
$TagVersion = "v$NewVersion"

Write-Host ""
Write-Host "Current version: $CurrentVersion" -ForegroundColor Cyan
Write-Host "New version: $NewVersion" -ForegroundColor Green
Write-Host "Tag: $TagVersion" -ForegroundColor Green
Write-Host ""

# Update VERSION file (without BOM)
$VersionPath = Join-Path (Get-Location) $VersionFile
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($VersionPath, $NewVersion, $Utf8NoBom)
Write-Host "Updated VERSION file" -ForegroundColor Green

# Detect default branch
$CurrentBranch = git rev-parse --abbrev-ref HEAD

# Try to get default branch from remote show
$DefaultBranch = $null
$RemoteInfo = git remote show origin 2>&1
$HeadLine = $RemoteInfo | Select-String 'HEAD branch'
if ($HeadLine) {
    $LineText = $HeadLine.Line
    if ($LineText -match 'HEAD branch:\s+(\S+)') {
        $DefaultBranch = $matches[1]
    }
}

# Fallback: check which remote branch exists
if (-not $DefaultBranch -or $DefaultBranch -eq "" -or $DefaultBranch -like "*http*") {
    $RemoteBranches = git branch -r
    if ($RemoteBranches | Select-String 'origin/master') {
        $DefaultBranch = "master"
    } elseif ($RemoteBranches | Select-String 'origin/main') {
        $DefaultBranch = "main"
    } else {
        $DefaultBranch = "master"
    }
}

# Require releases from default branch
if ($CurrentBranch -ne $DefaultBranch) {
    Write-Host "Error: Releases must be made from the default branch" -ForegroundColor Red
    Write-Host "Currently on: $CurrentBranch" -ForegroundColor Yellow
    Write-Host "Default branch: $DefaultBranch" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Please switch to the default branch first:" -ForegroundColor Cyan
    Write-Host "  git checkout $DefaultBranch" -ForegroundColor White
    Write-Host "  git pull origin $DefaultBranch" -ForegroundColor White
    git checkout $VersionFile
    exit 1
}

# Check for uncommitted changes - VERSION file is allowed
$UncommittedModified = git diff --name-only HEAD 2>$null | Where-Object { $_ -ne "VERSION" }
$UncommittedUntracked = git ls-files --others --exclude-standard | Where-Object { $_ -ne "VERSION" }
if ($UncommittedModified -or $UncommittedUntracked) {
    Write-Host "Warning: You have uncommitted changes" -ForegroundColor Yellow
    if ($UncommittedModified) {
        Write-Host "Modified files:" -ForegroundColor Yellow
        $UncommittedModified | ForEach-Object { Write-Host "  $_" }
    }
    if ($UncommittedUntracked) {
        Write-Host "Untracked files:" -ForegroundColor Yellow
        $UncommittedUntracked | ForEach-Object { Write-Host "  $_" }
    }
    $Prompt = "Continue with release anyway? [y/N]"
    $Continue = Read-Host $Prompt
    if ($Continue -ne "y" -and $Continue -ne "Y") {
        git checkout $VersionFile
        exit 1
    }
}

# Stage VERSION file
git add $VersionFile
Write-Host "Staged VERSION file" -ForegroundColor Green

# Commit
git commit -m "chore(release): $TagVersion"
Write-Host "Committed version bump" -ForegroundColor Green

# Create annotated tag
git tag -a $TagVersion -m $TagVersion
Write-Host "Created tag $TagVersion" -ForegroundColor Green

# Push default branch and tags
Write-Host ""
Write-Host "Pushing to origin/$DefaultBranch..." -ForegroundColor Cyan
git push origin $DefaultBranch
Write-Host "Pushed $DefaultBranch branch" -ForegroundColor Green

Write-Host "Pushing tags..." -ForegroundColor Cyan
git push origin $TagVersion
Write-Host "Pushed tag $TagVersion" -ForegroundColor Green

Write-Host ""
Write-Host "Release $TagVersion published!" -ForegroundColor Green
Write-Host ""
Write-Host "GitHub Actions will now:" -ForegroundColor Cyan
Write-Host "  - Validate version matches tag"
Write-Host "  - Build and push Docker images"
Write-Host "  - Tag images as: $TagVersion, $Major.$Minor, $Major, latest, main-<sha>"
