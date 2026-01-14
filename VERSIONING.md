# Versioning

Semantic versioning: `MAJOR.MINOR.PATCH`

- **MAJOR**: Breaking changes
- **MINOR**: New features
- **PATCH**: Bug fixes

Current version in `VERSION` file.

## Release

Run `.\scripts\release.ps1 patch` (or `minor`/`major`)

GitHub Actions:
- Validates VERSION matches tag
- Builds Docker image
- Pushes to ghcr.io with tags: `vX.Y.Z`, `X.Y`, `X`, `latest`, `main-<sha>`
