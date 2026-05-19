# PR Review Rubric

Every PR is audited by the `review` profile before merge. 
This document defines what the review profile checks, how it communicates, 
and when it escalates.

---

## 7-Point Review Checklist

The reviewer checks these seven items on every PR. Any check that fails results 
in a **request-changes** review.

### 1. Spec Compliance

Does the PR satisfy **every** acceptance criterion from the Kanban card body?

- [ ] Open the Kanban card: `hermes kanban show <card-id>`
- [ ] Read the acceptance criteria checklist
- [ ] Verify each item is satisfied by the PR's changes (not just checked off)
- [ ] If any criterion is unmet, request changes with a reference to the specific item

### 2. Architecture Adherence

Does the PR follow the rules in `ARCHITECTURE.md`?

- [ ] No duplicated parsers (DAT, DSBX, ZipCrypto)
- [ ] No inline ZipCrypto logic outside `web/lib/zipcrypto.py`
- [ ] Web routes use blueprints (after Phase 4), not bare `@app.route`
- [ ] Domain logic lives in `web/lib/`, not in route handlers
- [ ] No new .NET dependencies introduced without architectural justification

### 3. Test Coverage

Does the PR add tests for any new code?

- [ ] New functions in `web/lib/` have corresponding tests in `tests/`
- [ ] Edge cases are covered (empty input, malformed data, boundary values)
- [ ] Tests actually assert something meaningful (not just `pass`)
- [ ] **Reject if introducing untested code in `web/lib/` after P2-01 lands.**
- [ ] Before P2-01: recommend adding tests, but do not block on lack of coverage.

### 4. Code Quality

Is the code readable and maintainable?

- [ ] Clear, descriptive variable/function names (no single-letter names except loop indices)
- [ ] No dead code, no commented-out code blocks
- [ ] No `print()` debug statements left in
- [ ] Docstrings on public functions (one-liner for simple, full for complex)
- [ ] Consistent with project style (follow existing patterns)

### 5. Security

Are there any security issues?

- [ ] No hardcoded secrets (API keys, passwords, tokens)
- [ ] No SQL injection vectors (parameterized queries only)
- [ ] No `eval()`, `exec()`, or dynamic code execution on user input
- [ ] No shell injection (`os.system`, bare `subprocess` with user input)
- [ ] Proper input validation on all route parameters
- [ ] File operations use path sanitization (no path traversal)

### 6. No Scope Creep

Does the PR only touch files necessary for its card?

- [ ] Every changed file serves the card's stated goal
- [ ] No unrelated refactoring, formatting changes, or dependency bumps
- [ ] No bundled "while I was here" fixes — those get their own card
- [ ] If a drive-by fix is necessary to complete the card (e.g. a bug blocks the work), 
      note it explicitly in the PR description

### 7. CI Green

Does CI pass?

- [ ] Lint: ruff (Python), eslint (JS)
- [ ] Tests: `pytest`
- [ ] Build: Docker image builds
- [ ] Security: no leaked secrets
- [ ] **Reject if any CI check fails.**

---

## Review Actions

The review profile communicates through `gh pr review`. 
Three possible outcomes:

### Approve

```bash
gh pr review <num> --approve --body "Approved: <one-sentence summary of what was reviewed and why it's good>"
```

### Request Changes

```bash
gh pr review <num> --request-changes --body "## Issues

<specific issues with file paths and line references>

### Spec compliance
- [ ] <missing criterion> — see card <card-id>

### Architecture
- <violation and fix>

### Quality
- <issue and fix>
"
```

### Comment-Only Feedback

For non-blocking observations, suggestions, or questions:

```bash
gh pr review <num> --comment --body "<notes, suggestions, or questions>"
```

For line-level feedback, add a PR review comment via `gh api` or the GitHub UI.

---

## Escalation

If the reviewer is uncertain about an architectural decision, security tradeoff, 
or ambiguous specification, it **escalates** by blocking the Kanban card:

```bash
hermes kanban block <card-id> --reason "review-escalation: <specific question>"
```

This pauses the card until Tyler resolves the block. The reviewer then posts 
a comment on the Kanban card with detailed context:

```
hermes kanban comment <card-id> --body "Escalation details: ..."
```

Only escalate when:
- The correct approach is genuinely ambiguous
- There's a security implication that needs human judgment
- The PR reveals a gap in the spec (ARCHITECTURE.md or the card body)

Do NOT escalate for issues the reviewer can resolve independently 
(e.g. missing a test, poor naming, scope creep).

---

## Merge Authorization

A PR may be merged only when:
1. ✅ All 7 checklist items are satisfied
2. ✅ The review profile has approved (`gh pr review --approve`)
3. ✅ CI is green on the latest commit (re-run if changes were pushed after approval)

The worker who opened the PR performs the merge. Use squash-merge only:

```bash
gh pr merge <num> --squash --delete-branch
```
