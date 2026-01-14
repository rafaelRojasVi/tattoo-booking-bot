# PowerShell version bumping script
# Usage: .\scripts\bump-version.ps1 [major|minor|patch]

param(
    [Parameter(Position=0)]
    [ValidateSet("major", "minor", "patch")]
    [string]$BumpType = "patch"
)

$VersionFile = "VERSION"

if (-not (Test-Path $VersionFile)) {
    "0.0.0" | Out-File -FilePath $VersionFile -Encoding utf8
}

$CurrentVersion = (Get-Content $VersionFile).Trim()
$VersionParts = $CurrentVersion -split '\.'
$Major = [int]$VersionParts[0]
$Minor = [int]$VersionParts[1]
$Patch = [int]$VersionParts[2]

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
$NewVersion | Out-File -FilePath $VersionFile -Encoding utf8

Write-Host "Version bumped from $CurrentVersion to $NewVersion" -ForegroundColor Green
Write-Host ""
Write-Host "Don't forget to commit and tag:" -ForegroundColor Yellow
Write-Host "  git add VERSION"
Write-Host "  git commit -m 'Bump version to $NewVersion'"
Write-Host "  git tag -a v$NewVersion -m 'Version $NewVersion'"
Write-Host "  git push origin main --tags"
