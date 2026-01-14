#!/bin/bash
# Release script - bumps version, commits, tags, and pushes
# Usage: ./scripts/release.sh [patch|minor|major]

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 [patch|minor|major]"
    exit 1
fi

BUMP_TYPE=$1

if [[ ! "$BUMP_TYPE" =~ ^(patch|minor|major)$ ]]; then
    echo "Error: Bump type must be 'patch', 'minor', or 'major'"
    exit 1
fi

VERSION_FILE="VERSION"

if [ ! -f "$VERSION_FILE" ]; then
    echo "Error: VERSION file not found"
    exit 1
fi

# Get current version
CURRENT_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
IFS='.' read -ra VERSION_PARTS <<< "$CURRENT_VERSION"
MAJOR=${VERSION_PARTS[0]}
MINOR=${VERSION_PARTS[1]}
PATCH=${VERSION_PARTS[2]}

# Bump version
case $BUMP_TYPE in
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    patch)
        PATCH=$((PATCH + 1))
        ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
TAG_VERSION="v$NEW_VERSION"

echo "Current version: $CURRENT_VERSION"
echo "New version: $NEW_VERSION"
echo "Tag: $TAG_VERSION"
echo ""

# Update VERSION file
echo "$NEW_VERSION" > "$VERSION_FILE"
echo "✓ Updated VERSION file"

# Check if we're on main branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "Warning: You're not on the 'main' branch (currently on '$CURRENT_BRANCH')"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        git checkout "$VERSION_FILE"  # Revert VERSION file
        exit 1
    fi
fi

# Check for uncommitted changes (excluding VERSION)
if ! git diff --quiet HEAD -- ':!VERSION'; then
    echo "Error: You have uncommitted changes. Please commit or stash them first."
    exit 1
fi

# Stage VERSION file
git add "$VERSION_FILE"
echo "✓ Staged VERSION file"

# Commit
git commit -m "chore(release): $TAG_VERSION"
echo "✓ Committed version bump"

# Create annotated tag
git tag -a "$TAG_VERSION" -m "$TAG_VERSION"
echo "✓ Created tag $TAG_VERSION"

# Push main and tags
echo ""
echo "Pushing to origin/main..."
git push origin main
echo "✓ Pushed main branch"

echo "Pushing tags..."
git push origin "$TAG_VERSION"
echo "✓ Pushed tag $TAG_VERSION"

echo ""
echo "🎉 Release $TAG_VERSION published!"
echo ""
echo "GitHub Actions will now:"
echo "  - Validate version matches tag"
echo "  - Build and push Docker images"
echo "  - Tag images as: $TAG_VERSION, $MAJOR.$MINOR, $MAJOR, latest, main-<sha>"
