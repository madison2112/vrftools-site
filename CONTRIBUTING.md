# Contributing to vrf-tools

This is the refactor repo for VRFTools, deployed to tranesubishi.com. 
It is sister to `central-control-database-tools` (the live site at vrftools.com).

Every Kanban card on the `vrf-tools-refactor` board produces one PR against this repo.
Follow these rules so every worker and the review profile operate consistently.

## Branch Naming Convention

```
refactor/<card-id>-<short-slug>
```

- `<card-id>` — from the Kanban board (e.g. `b-01`, `p0-06`, `lf-12`). Always lowercase.
- `<short-slug>` — 2–5 kebab-case words summarizing the change. Max ~50 chars total.

Examples:

- `refactor/b-01-backend-quick-wins`
- `refactor/dl-09-dat-blueprint`
- `refactor/mf-03-mtdz-report-table`
- `refactor/p0-06-contributing-docs`

## Commit Format

```
<phase-id>: <description>
```

- `<phase-id>` — matches the card ID prefix (e.g. `P0-06`, `B-01`, `DL-03`, `LF-12`, `MF-07`).
- `<description>` — sentence case, no trailing period.

Examples:

- `P0-06: add CONTRIBUTING + PR template + BACKPORT/REVIEW docs`
- `B-01: use hmac.compare_digest for agent key check`
- `DL-09: extract DAT header parser into DatHeader class`

One logical change per commit. Multiple commits per PR are fine if each represents
a discrete step, but prefer a single well-structured commit for straightforward cards.

## PR Rules

- **One card → one branch → one PR.** Never combine multiple cards in a single PR.
- **PR title = card title** (copy verbatim from the Kanban card).
- **PR description MUST include:**
  - `Card: t_xxxxxxxx` (the Kanban card ID)
  - Acceptance criteria checklist copied from the card body (tick items as you complete them)
- **Squash-merge only** — never merge-commit, never rebase-merge.
- **Delete the branch after merge.**
- PRs open against `main`.

## Review Flow

1. Worker creates branch from `main`, does the work, pushes, opens a PR.
2. CI runs automatically (lint + tests).
3. The `review` profile audits the PR — see `docs/REVIEW.md` for the rubric.
4. If the review approves **and** CI passes → the worker (or orchestrator) squash-merges.
5. Worker deletes the remote branch (GitHub auto-deletes if configured).
6. Worker marks the Kanban card complete with a summary and metadata.

If the review requests changes:
1. Worker pushes fixes to the same branch. The PR updates automatically.
2. Re-request review via `gh pr ready <num>` or a comment.
3. Go back to step 3.

If the review escalates (blocked for a human decision):
1. The reviewer blocks the Kanban card via `hermes kanban block <id> --reason "review-escalation: <question>"`.
2. Tyler resolves the block (comment + `hermes kanban unblock <id>`).
3. The worker picks up again on the unblock re-spawn.

## CI Expectations

CI runs these checks on every PR:
- **Lint** — ruff (Python), eslint (JS)
- **Tests** — `pytest` (Python)
- **Build** — Docker image builds successfully
- **Security** — no hardcoded secrets (trivy or secret-scan)

A PR that does not pass CI will not be reviewed. Fix CI failures before requesting review.

## Backport Policy

For bug fixes that also exist on the live site, use the procedure in `docs/BACKPORT.md`.
Do not cherry-pick across repos — they diverge after commit `3c78dfd`.

Only bug fixes are backported. Refactor improvements (blueprint extractions, code 
reorganization, new features) stay in this repo.

## Quick Reference

```bash
# Start a card
git checkout main
git checkout -b refactor/<card-id>-<slug>

# Commit
git add <files>
git commit -m "<phase-id>: <description>"

# Push and open PR
git push origin refactor/<card-id>-<slug>
gh pr create \
  --title "<card title>" \
  --body-file .github/PULL_REQUEST_TEMPLATE.md \
  --base main
```
