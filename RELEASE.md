# Release

Run one command:

**Windows:**
```powershell
.\scripts\release.ps1 patch
```

**Linux/Mac:**
```bash
./scripts/release.sh patch
```

Options: `patch`, `minor`, or `major`

That's it. The script bumps version, commits, tags, and pushes. GitHub Actions builds and publishes Docker images automatically.
