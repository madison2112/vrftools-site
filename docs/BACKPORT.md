# Backport & Forward-Port Guide

Both the refactor repo (`vrf-tools`, this repo) and the live-site repo 
(`central-control-database-tools`) share history up to commit `3c78dfd`.

After that commit, they diverge:

- **vrf-tools** — refactor work, deploys to tranesubishi.com
- **central-control-database-tools** — live site, deploys to vrftools.com / codetest.vrftools.com

Bug fixes found during the refactor may also affect the live site. This document 
covers moving fixes between repos.

> **Do NOT use `git cherry-pick` across these repos.** They have different commit 
> history after the divergence point. `cherry-pick` will produce garbled results.

---

## Backport: vrf-tools → central-control-database-tools

Use this when a BUG FIX discovered during refactor work also needs to be applied 
to the live site.

```bash
# 1. From the refactor repo, export the fix commit as a patch
cd /home/claudecode/vrf-tools
git format-patch -1 <commit-sha> --stdout > /tmp/patch.diff

# 2. Apply to the live-site repo
cd /home/claudecode/central-control-database-tools
git checkout main
git checkout -b backport/<description>
git apply --3way /tmp/patch.diff

# 3. Resolve any conflicts manually, then commit
git add -A
git commit -m "backport: <description> (from vrf-tools <sha>)"

# 4. Push and open PR against the live site
git push origin backport/<description>
gh pr create \
  --title "Backport: <description>" \
  --body "Backported from vrf-tools commit <sha>.
          See original PR: https://github.com/madison2112/vrftools-site/pull/<num>"
```

### If the patch fails to apply

Paths may have changed during refactor (e.g. `app.py` → `web/lib/dat_utils.py`).

When `git apply` fails:
1. Open the patch file (`/tmp/patch.diff`) to see the original change.
2. Find the equivalent file in the live-site repo (path may differ).
3. Manually reapply the logic in the target file.
4. Reference the original commit in the new commit message:
   ```
   backport: <description> (manual; from vrf-tools <sha>)
   ```

---

## Forward-Port: central-control-database-tools → vrf-tools

Use this when a bug fix lands on the live site first and should be incorporated 
into the refactor.

```bash
# 1. From the live-site repo, export the fix commit as a patch
cd /home/claudecode/central-control-database-tools
git format-patch -1 <commit-sha> --stdout > /tmp/patch.diff

# 2. Apply to the refactor repo
cd /home/claudecode/vrf-tools
git checkout main
git checkout -b forward-port/<description>
git apply --3way /tmp/patch.diff

# 3. Resolve conflicts and commit
git add -A
git commit -m "forward-port: <description> (from central-control-database-tools <sha>)"

# 4. Push and open PR
git push origin forward-port/<description>
gh pr create \
  --title "Forward-port: <description>" \
  --body "Forward-ported from central-control-database-tools commit <sha>."
```

### If the patch fails to apply

The refactor may have moved or restructured files. 
When `git apply` fails:
1. Read the original commit: `git show <sha>` in the live-site repo.
2. Identify the equivalent code in the refactor repo.
3. Manually reapply the logic, respecting the refactor's structure.
4. Reference the original commit:
   ```
   forward-port: <description> (manual; from central-control-database-tools <sha>)
   ```

---

## What Gets Ported

| Port | Always |
|------|--------|
| Bug fixes | ✅ |
| Security patches | ✅ |
| Refactor improvements | ❌ |
| New features | ❌ |
| Blueprint extractions | ❌ |
| Code reorganization | ❌ |
| Documentation | Only if it corrects factual errors on the live site |

---

## Common Mistakes

- **Don't `git cherry-pick` across repos.** The commit histories diverge after `3c78dfd` — cherry-pick assumes a shared commit DAG.
- **Don't backport refactor-only changes.** Blueprint classes, new module layouts, and dependency updates are meaningless on the live site.
- **Don't port without testing.** Always run `pytest` in the TARGET repo before opening the PR.
- **Don't assume file paths match.** The refactor moves files. Read `ARCHITECTURE.md` to find where code lives in each repo.

---

## Verification

After backporting, verify the fix works in the target context:

```bash
cd /home/claudecode/central-control-database-tools
pytest tests/
# Confirm the test for the backported fix passes
```
