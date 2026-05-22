# HANDOFF — VRFTools Refactor

Living document of handoff notes for the `vrf-tools-refactor` Kanban board. Sections are added as they become needed; gaps in the numbering are intentional (each section is a discrete handoff and is referenced elsewhere by its number).

Current sections:

- §6 — MTDZ Refactor Scope
- §7 — Audience & Viewport Policy

---

## 6. MTDZ Refactor Scope

This section bounds the MF-## card stream (MF-01 through MF-18) and clarifies which repository they target. **Read this before dispatching any MF-## worker.**

### Target repo & paths — IN scope

MF-## items target the **in-tree web-app MTDZ tool** inside this repository:

- `web/static/js/mtdz/` — MTDZ frontend JavaScript
- `web/templates/mtdz/` — MTDZ Jinja templates
- Related blueprint code in `web/lib/` once MTDZ routes are extracted

Deploys to `tranesubishi.com` via this repo's pipeline.

### What is NOT in scope

- **`/home/claudecode/MTDZ-Viewer/`** — the standalone .NET-backed diagnostic viewer project is a separate Docker stack with its own git repo. Whether it joins the refactor at all is a Tyler decision, not a worker decision. Do not branch, edit, or open PRs there for MF-## work.
- **`/home/claudecode/central-control-database-tools/`** — the live site repo. Bug fixes only during the refactor; never the target for MF-## items.

### Topics in scope for the current MF-## cards

A11y polish, focus management, ARIA correctness, modal behavior, responsive layout, basic JS scoping cleanup (IIFE wrapping, global elimination), template inheritance fixes.

### Topics out of scope unless a new MF card is added

Parser changes, backend route moves, new diagnostic features, .NET DLL extraction-layer changes, schema changes, persistence work.

### Why this section exists (P1-D miscarry, 2026-05-20)

P1-D (MF-01..MF-05) was originally merged into the wrong repo (`MTDZ-Viewer` PR #1) because the worker found the standalone `MTDZ-Viewer` folder and assumed it was the target. The previous orchestrator compounded the error by editing the plan doc (FOREMAN-04) and the project CLAUDE.md to validate the wrong assumption.

Resolution: port-forward the P1-D diffs into `vrf-tools/` (option a, 2026-05-20).

The lesson: **when dispatching an MF-## card, the card body must name the exact target repo and path.** Do not let workers infer from folder names. If a worker reports finding MTDZ frontend files in `MTDZ-Viewer/`, that is NOT the MF-## target.

### Pointer for newcomers

- Live-site MTDZ (different concern): see memory `reference_mtdz_frontend_layout` — the live site (`central-control-database-tools` deployed at vrftools.com) serves its own MTDZ copy. Editing that one belongs to the bug-fix lane against the live-site repo, not to the refactor.

---

## 7. Audience & Viewport Policy

**VRFTools targets desktop browsers only.** Mobile responsiveness is a non-goal.

### Why

The audience is HVAC commissioning engineers, who work at desks with physical keyboards and multi-monitor setups. The web app's value-add over the Mitsubishi Windows desktop tool is platform independence (Mac, Linux, no install) — not phone usability. There is no real-world mobile use case for these tools.

### What this means for workers

- Do NOT add mobile breakpoints, responsive layouts, viewport-specific behavior, or "test on mobile" acceptance criteria to new work.
- The existing `isMobile()` hard blocks in `web/static/js/mtdz/viewer.js` and `web/static/js/mtdz/sysinfo.js` are **correct**. Do not "fix" them.
- Accessibility (keyboard navigation, screen readers, ARIA, focus management) IS a priority. These are viewport-agnostic and not in tension with this policy. Continue treating a11y work (the LF-09 / MF-08 pattern) as in scope.

### Items removed from refactor scope (2026-05-22)

- `MF-10` — Replace `isMobile()` hard blocks with responsive MTDZ layouts
- `MF-11` — Responsive CSS for MTDZ pages
- `HC-07` — Unified responsive design strategy

The Obsidian plan documents have been annotated with the removal.

### Already-shipped responsive work

The LEV Kit frontend already shipped responsive breakpoints in LF-06, LF-07, and LF-08 (P2-C and P3-B). That work is **not** being reverted — it doesn't hurt desktop users and ripping it out would be net-negative churn. Treat it as completed-and-frozen. Do not extend it.
