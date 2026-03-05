# Branch Protection Setup

This repository uses CI gates from `.github/workflows/ci.yml`.

Configure GitHub branch protection for `main`:

1. Open repository `Settings -> Branches -> Add rule`.
2. Branch name pattern: `main`.
3. Enable `Require a pull request before merging`.
4. Enable `Require status checks to pass before merging`.
5. Select required checks:
   - `Lint (ruff)`
   - `Tests (unittest + pytest)`
   - `Coverage (pytest)`
   - `Build smoke (Windows)`
6. Enable `Require branches to be up to date before merging`.
7. Enable `Do not allow bypassing the above settings` (recommended).

After configuration, direct pushes to `main` should be blocked.

## Optional API automation

You can apply the same rule via GitHub API:

```powershell
$env:GITHUB_TOKEN = "<token with repo admin permission>"
powershell -NoProfile -ExecutionPolicy Bypass -File .\set_branch_protection.ps1
```

Script location: `set_branch_protection.ps1`.
