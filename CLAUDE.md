# CLAUDE.md — vrf-tools (Refactor Target)

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠ This Is The Refactor Repo

**This repository is the active refactor target for VRFTools.** It deploys to **tranesubishi.com**.

For **bug fixes to the live site** (vrftools.com / codetest.vrftools.com), use the OTHER repo:
- Live-site repo: `/home/claudecode/central-control-database-tools/`
- Live-site remote: `https://github.com/madison2112/central-control-database-tools`

Do NOT cross-port code between repos without going through the documented backport procedure
(see `docs/BACKPORT.md` once it exists).

## Repository Identity

- **GitHub**: https://github.com/madison2112/vrftools-site
- **Default branch**: `main`
- **Local path**: `/home/claudecode/vrf-tools/`
- **Deploys to**: `tranesubishi.com`
- **Sister repo (live site)**: `central-control-database-tools` → `codetest.vrftools.com` / `vrftools.com`

The two repos share commit ancestry up to commit `3c78dfd` (pre-refactor WIP snapshot).
After that point they diverge: live-site fixes go to the sister repo; refactor work goes here.

## Refactor Plan

The full refactor is planned in the Obsidian vault under:

- `Resources/VRFTools Refactor Plan — Holistic Integration.md` (coordinator)
- `Resources/VRFTools Refactor Plan — Backend.md` (B-01 → B-22)
- `Resources/VRFTools Refactor Plan — Domain Logic.md` (DL-01 → DL-25)
- `Resources/VRFTools Refactor Plan — LEV Kit Frontend.md` (LF-01 → LF-18)
- `Resources/VRFTools Refactor Plan — MTDZ Frontend.md` (MF-01 → MF-18)

Execution is tracked on the **`vrf-tools-refactor`** Kanban board.
Run `hermes kanban list --board vrf-tools-refactor` to see active cards.

## Project Overview

VRFTools is an unofficial Mitsubishi Electric HVAC utilities web app. The Flask backend
exposes file-format tools (DAT/DSBX/JSON conversion, LEV Kit configurator, MTDZ diagnostic
viewer) used by HVAC commissioning engineers. Underneath, this repo also contains
ISToolAEC configuration files for the AE-C400 controller — see `AE-C400 Initial Setting
Tool Software/` for the desktop tooling that informs the web format.

## Key Application Directories

- `web/app.py` — Flask app entry point (currently a 1355-line monolith, to be broken into blueprints in Phase 4)
- `web/lib/` — Domain logic modules (`dat_utils.py`, `dsbx_utils.py`, `zipcrypto.py`, `lev_kit_utils.py`, `json_utils.py`, `sessions.py`, `agent_routes.py`)
- `web/templates/` — Jinja2 templates (config tools + LEV Kit + MTDZ sub-app)
- `web/static/` — CSS, JS, assets
- `tests/` — pytest test suite (sparse — to be expanded in Phase 2)
- `templates/` (repo root) — DAT template files used by domain logic
- `Empty Configs/` — Sample empty configuration files for AE-C400 controller types
- `AE-C400 Initial Setting Tool Software/` — Mitsubishi's ISToolAEC desktop app + lookup tables (not deployed)

## Reference Material (Mitsubishi Desktop Tooling)

These files are reference for understanding the binary formats this web app reads/writes. They
are not deployed and not modified by the refactor.

- `AE-C400 Config Empty.dat` / `AE-C400 Config Filled.dat` — example HVAC unit config exports
  (ZIP archives despite the `.dat` extension — internal entry is password-protected with `MELCO`)
- `Group Names.txt` — 50 group name entries in `F##_<name>` format
- `AE-C400 Initial Setting Tool Software/ISToolAEC.exe` — Mitsubishi's GUI (.NET 4.0)
- `AE-C400 Initial Setting Tool Software/Data/*.dat` — CSV lookup tables for unit model catalog,
  Modbus register mappings, etc.

## Workflow

1. Every refactor card → its own branch `refactor/<card-id>-<slug>` → its own PR → squash-merge to `main`
2. The `review` profile (Claude Sonnet 4.6) audits each PR before merge
3. Major milestones block for human (Tyler) review
4. Conventions documented in `CONTRIBUTING.md` (created by P0-06)
