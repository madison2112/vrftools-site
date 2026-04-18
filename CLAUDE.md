# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a configuration workspace for Mitsubishi Electric **AE-C400** HVAC controller systems using the **ISToolAEC** (Initial Settings Tool). There is no source code to build — the tool is a pre-compiled .NET 4.0 application.

The workflow is: create/edit a `.dat` config file → load it into `ISToolAEC.exe` → write settings to connected AE-C400 hardware.

## Key Files

- `AE-C400 Config Empty.dat` / `AE-C400 Config Filled.dat` — HVAC unit configuration exports. These are **ZIP archives** despite the `.dat` extension. Unzipping them reveals the actual settings payload.
- `Group Names.txt` — 50 group name entries in `F##_<name>` format, one per line, indexed 1–50.
- `AE-C400 Initial Setting Tool Software/ISToolAEC.exe` — Main GUI application. Requires .NET Framework 4.0.
- `AE-C400 Initial Setting Tool Software/Config.exe` — Auxiliary configuration utility (.NET 4.8).

## Data Directory (CSV Lookup Tables)

All files under `AE-C400 Initial Setting Tool Software/Data/` are UTF-8 BOM CSV tables used by the tool at runtime:

- `modelType.dat` / `modelTypeJP.dat` — HVAC indoor unit model catalog (`ModelTypeID, ModelTypeName, Attribute, ModelTypeDisplayID`)
- `modelData.dat` / `modelDataJP.dat` — Extended model parameter data
- `modbusUnitTable.dat` — Modbus register mappings for unit communication

## Runtime Configuration

`ISToolAEC.exe.config` controls runtime behavior:
- `TempUnit`: `F` (Fahrenheit) or `C`
- `Country`: `na` (North America) or other region codes
- `LogLevel`: `debug` / `info` / etc.
- `SetCharge`: `true`/`false` — enables refrigerant charge settings

## Config File Format

`.dat` config files are password-protected ZIP archives. To inspect contents: `unzip -l "AE-C400 Config Filled.dat"`. The single internal entry has a filename matching the 16-character hex serial stored at offset `0x12` in the ZIP local file header.
