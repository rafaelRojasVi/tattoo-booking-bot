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

# Get current version
$CurrentVersion = (Get-Content $VersionFile).Trim()
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

# Update VERSION file
$NewVersion | Out-File -FilePath $VersionFile -Encoding utf8 -NoNewline
Write-Host "✓ Updated VERSION file" -ForegroundColor Green

# Detect default branch from remote
$CurrentBranch = git rev-parse --abbrev-ref HEAD
$DefaultBranch = $null

# Try to get default branch from remote HEAD
$RemoteHead = git symbolic-ref refs/remotes/origin/HEAD 2>$null
if ($RemoteHead) {
    $DefaultBranch = $RemoteHead -replace 'refs/remotes/origin/', ''
} else {
    # Fallback: check remote show output
    $RemoteInfo = git remote show origin 2>$null
    if ($RemoteInfo) {
        $HeadLine = $RemoteInfo | Select-String 'HEAD branch'
        if ($HeadLine) {
            $DefaultBranch = ($HeadLine -split ':')[1].Trim()
        }
    }
}

# Final fallback: try common defaults
if (-not $DefaultBranch) {
    if (git show-ref --verify --quiet refs/heads/master) {
        $DefaultBranch = "master"
    } elseif (git show-ref --verify --quiet refs/heads/main) {
        $DefaultBranch = "main"
    } else {
        $DefaultBranch = "master"  # ultimate fallback
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
    git checkout $VersionFile  # Revert VERSION file
    exit 1
}

# Check for uncommitted changes (not including VERSION)
$UncommittedModified = git diff --name-only HEAD 2>$null | Where-Object { $_ -ne "VERSION" }
$UncommittedUntracked = git ls-files --others --exclude-standard | Where-Object { $_ -ne "VERSION" }
if ($UncommittedModified -or $UncommittedUntracked) {
    Write-Host "Warning: You have uncommitted changes (excluding VERSION)" -ForegroundColor Yellow
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
        git checkout $VersionFile  # Revert VERSION file
        exit 1
    }
}

# Stage VERSION file
git add $VersionFile
Write-Host "✓ Staged VERSION file" -ForegroundColor Green

# Commit
git commit -m "chore(release): $TagVersion"
Write-Host "✓ Committed version bump" -ForegroundColor Green

# Create annotated tag
git tag -a $TagVersion -m $TagVersion
Write-Host "✓ Created tag $TagVersion" -ForegroundColor Green

# Push default branch and tags
Write-Host ""
Write-Host "Pushing to origin/$DefaultBranch..." -ForegroundColor Cyan
git push origin $DefaultBranch
Write-Host "✓ Pushed $DefaultBranch branch" -ForegroundColor Green

Write-Host "Pushing tags..." -ForegroundColor Cyan
git push origin $TagVersion
Write-Host "✓ Pushed tag $TagVersion" -ForegroundColor Green

Write-Host ""
Write-Host "🎉 Release $TagVersion published!" -ForegroundColor Green
Write-Host ""
Write-Host "GitHub Actions will now:" -ForegroundColor Cyan
Write-Host "  - Validate version matches tag"
Write-Host "  - Build and push Docker images"
Write-Host "  - Tag images as: $TagVersion, $Major.$Minor, $Major, latest, main-<sha>"
