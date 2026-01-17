# GitHub Push Instructions (Without Versioning)

## Prerequisites

1. Make sure all tests pass:
   ```powershell
   pytest tests/ -v
   ```

2. Review your changes:
   ```powershell
   git status
   git diff
   ```

## Step-by-Step Push Process

### 1. Stage All Changes

**Windows (PowerShell):**
```powershell
git add .
```

**Linux/Mac (Bash):**
```bash
git add .
```

### 2. Commit Changes (No Version Bump)

**Windows (PowerShell):**
```powershell
git commit -m "feat: align codebase with v1.4 proposal

- Add all missing Lead database fields (location, deposit, booking, timestamps)
- Expand status model to match proposal (PENDING_APPROVAL, DEPOSIT_PAID, etc.)
- Update conversation flow to use PENDING_APPROVAL after qualification
- Implement webhook idempotency (ProcessedMessage table)
- Add WhatsApp dry-run feature flag
- Update questions to include location and size category selection
- Add ARTIST handover and CONTINUE resume handlers
- Add comprehensive tests for new features
- Create migration for new database fields"
```

**Linux/Mac (Bash):**
```bash
git commit -m "feat: align codebase with v1.4 proposal

- Add all missing Lead database fields (location, deposit, booking, timestamps)
- Expand status model to match proposal (PENDING_APPROVAL, DEPOSIT_PAID, etc.)
- Update conversation flow to use PENDING_APPROVAL after qualification
- Implement webhook idempotency (ProcessedMessage table)
- Add WhatsApp dry-run feature flag
- Update questions to include location and size category selection
- Add ARTIST handover and CONTINUE resume handlers
- Add comprehensive tests for new features
- Create migration for new database fields"
```

### 3. Check Current Branch

```powershell
git branch
```

Make sure you're on the branch you want to push (usually `master` or `main`).

### 4. Push to GitHub

**If pushing to master:**
```powershell
git push origin master
```

**If pushing to main:**
```powershell
git push origin main
```

**If you need to set upstream (first time):**
```powershell
git push -u origin master
# or
git push -u origin main
```

## Alternative: Push to Feature Branch

If you want to push to a feature branch instead:

### 1. Create and Switch to Feature Branch

```powershell
git checkout -b feat/v1.4-proposal-alignment
```

### 2. Stage, Commit, and Push

```powershell
git add .
git commit -m "feat: align codebase with v1.4 proposal"
git push -u origin feat/v1.4-proposal-alignment
```

## Verify Push

After pushing, verify on GitHub:
1. Go to your repository on GitHub
2. Check the latest commit appears
3. Verify all files are present

## What NOT to Do (No Versioning)

- ❌ Don't run `.\scripts\release.ps1` (that bumps version and creates tags)
- ❌ Don't modify the `VERSION` file
- ❌ Don't create git tags
- ✅ Just commit and push normally

## Files Changed (Summary)

### Modified Files
- `app/db/models.py` - Added new fields and ProcessedMessage model
- `app/services/conversation.py` - Updated status handling, ARTIST/CONTINUE
- `app/api/webhooks.py` - Added idempotency, dry-run flag
- `app/core/config.py` - Added whatsapp_dry_run setting
- `app/services/questions.py` - Updated question set
- `tests/test_conversation.py` - Updated for new statuses
- `tests/conftest.py` - Updated for new models

### New Files
- `migrations/versions/a1b2c3d4e5f6_add_proposal_v1_4_fields.py` - Migration
- `tests/test_conversation_new_features.py` - New feature tests
- `tests/test_webhook_idempotency.py` - Idempotency tests
- `tests/test_new_database_fields.py` - Database field tests
- `tests/test_questions_updated.py` - Question tests
- `IMPLEMENTATION_STATUS.md` - Implementation status document
- `TEST_RUN_INSTRUCTIONS.md` - Test instructions
- `GITHUB_PUSH_INSTRUCTIONS.md` - This file

## If Push Fails

### Authentication Issues

If you get authentication errors:
1. Check your GitHub credentials
2. Use SSH instead of HTTPS:
   ```powershell
   git remote set-url origin git@github.com:your-username/tattoo-booking-bot.git
   ```

### Branch Protection

If you get "branch is protected" errors:
- Push to a feature branch first
- Create a Pull Request on GitHub
- Merge via PR

### Conflicts

If you get merge conflicts:
```powershell
git pull origin master
# Resolve conflicts
git add .
git commit -m "fix: resolve merge conflicts"
git push origin master
```
