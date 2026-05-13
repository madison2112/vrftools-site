"""
LEV Kit Configurator backend logic.

Pure-Python module: no Flask imports, no I/O side effects beyond what callers pass in.

Covers:
  - PAC-AH002 (R32 LEV Kit) DIP switch generation, ported from v4.6 HTML tool.
  - PAC-AH001 (R-410A LEV Kit) DIP switch generation, ported from the AH001
    React reference (pac-ah001-configurator.html) with SW5 voltage addition.
  - .dsbx file parsing (Mitsubishi DSB project export, ZIP-wrapped XML).
  - Submittal PDF rendering (ReportLab).

Public API:
  CAPACITY_OPTIONS, THERMO_OPTIONS, HEATING_SETPOINT_OPTIONS  - AH002 lookup tables
  CAPACITY_OPTIONS_AH001, THERMO_OPTIONS_AH001,
    DAT_SETPOINT_OPTIONS_AH001                                - AH001 lookup tables
  CONTROLLER_AH001, CONTROLLER_AH002, REFRIGERANT_LABEL       - controller IDs
  generate_switch_positions(config)                           - per-unit switch calc
                                                                (dispatches on
                                                                 config['controller_type'])
  parse_dsbx(file_bytes)                                      - dsbx -> dict
  build_unit_record(parsed_unit, **overrides)                 - ready-for-PDF unit
  render_submittal_pdf(units, project_name, voltage, layout)  - bytes
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# Controller identifiers
# ---------------------------------------------------------------------------

CONTROLLER_AH001 = "PAC-AH001"
CONTROLLER_AH002 = "PAC-AH002"

REFRIGERANT_LABEL = {
    CONTROLLER_AH001: "R-410A",
    CONTROLLER_AH002: "R-32",
}


# ---------------------------------------------------------------------------
# AH002 (R-32) lookup tables (verbatim port from pac-ah002-configurator-v4.6.html)
# ---------------------------------------------------------------------------

CAPACITY_OPTIONS: list[dict] = [
    {"value":  0, "label": "--- LEV Kit Size ---", "btuh":      0, "lev": "--- Not Selected ---", "sw2": [0, 0, 0, 0, 0, 0]},
    {"value":  1, "label": "6 MBH",                "btuh":   6000, "lev": "PAC-LV24AC-1",          "sw2": [0, 0, 1, 0, 0, 0]},
    {"value":  2, "label": "8 MBH",                "btuh":   8000, "lev": "PAC-LV24AC-1",          "sw2": [1, 0, 1, 0, 0, 0]},
    {"value":  3, "label": "12 MBH",               "btuh":  12000, "lev": "PAC-LV24AC-1",          "sw2": [0, 1, 1, 0, 0, 0]},
    {"value":  4, "label": "15 MBH",               "btuh":  15000, "lev": "PAC-LV24AC-1",          "sw2": [0, 0, 0, 1, 0, 0]},
    {"value":  5, "label": "18 MBH",               "btuh":  18000, "lev": "PAC-LV24AC-1",          "sw2": [0, 1, 0, 1, 0, 0]},
    {"value":  6, "label": "24 MBH",               "btuh":  24000, "lev": "PAC-LV24AC-1",          "sw2": [1, 0, 1, 1, 0, 0]},
    {"value":  7, "label": "27 MBH",               "btuh":  27000, "lev": "PAC-LV48AC-1",          "sw2": [0, 1, 1, 1, 0, 0]},
    {"value":  8, "label": "30 MBH",               "btuh":  30000, "lev": "PAC-LV48AC-1",          "sw2": [0, 0, 0, 0, 1, 0]},
    {"value":  9, "label": "36 MBH",               "btuh":  36000, "lev": "PAC-LV48AC-1",          "sw2": [0, 0, 1, 0, 1, 0]},
    {"value": 10, "label": "48 MBH",               "btuh":  48000, "lev": "PAC-LV48AC-1",          "sw2": [1, 0, 0, 1, 1, 0]},
    {"value": 11, "label": "54 MBH",               "btuh":  54000, "lev": "PAC-LV60AC-1",          "sw2": [0, 0, 1, 1, 1, 0]},
    {"value": 12, "label": "60 MBH",               "btuh":  60000, "lev": "PAC-LV60AC-1",          "sw2": [1, 1, 1, 1, 1, 0]},
    {"value": 13, "label": "72 MBH",               "btuh":  72000, "lev": "PAC-LV96AC-1",          "sw2": [0, 0, 0, 1, 0, 1]},
    {"value": 14, "label": "96 MBH",               "btuh":  96000, "lev": "PAC-LV96AC-1",          "sw2": [0, 1, 0, 0, 1, 1]},
    {"value": 15, "label": "120 MBH",              "btuh": 120000, "lev": "PAC-LV120AC-1",         "sw2": [0, 0, 1, 1, 1, 1]},
    {"value": 16, "label": "144 MBH",              "btuh": 144000, "lev": "PAC-LV96AC-1 (x2)",     "sw2": [0, 0, 0, 0, 1, 0]},
    {"value": 17, "label": "168 MBH",              "btuh": 168000, "lev": "PAC-LV96AC-1 (x2)",     "sw2": [0, 1, 0, 1, 1, 0]},
    {"value": 18, "label": "192 MBH",              "btuh": 192000, "lev": "PAC-LV96AC-1 (x2)",     "sw2": [0, 0, 1, 0, 0, 1]},
    {"value": 19, "label": "216 MBH",              "btuh": 216000, "lev": "PAC-LV120AC-1 (x2)",    "sw2": [0, 1, 1, 1, 0, 1]},
    {"value": 20, "label": "240 MBH",              "btuh": 240000, "lev": "PAC-LV120AC-1 (x2)",    "sw2": [0, 0, 0, 1, 1, 1]},
]

THERMO_OPTIONS: list[dict] = [
    {"value": 2, "label": "Thermo OFF at 82°F (Default)", "sw3": [1, 0]},
    {"value": 3, "label": "Thermo OFF at 70°F",           "sw3": [0, 0]},
    {"value": 4, "label": "Thermo OFF at 59°F",           "sw3": [1, 1]},
    {"value": 1, "label": "Thermo OFF at 50°F",           "sw3": [0, 1]},
]

HEATING_SETPOINT_OPTIONS: list[dict] = [
    {"value": 2, "label": "Heating Setpoint Upper Limit: 95°F (Default)"},
    {"value": 1, "label": "Heating Setpoint Upper Limit: 82°F"},
]

DEFAULT_SWITCHES: dict[str, list[int]] = {
    "SW1":  [0, 0, 0, 0, 0, 0, 0, 0, 1, 0],
    "SW2":  [0, 0, 0, 0, 0, 0],
    "SW3":  [0, 0, 0, 0, 1, 0, 0, 1, 0, 1],
    "SW4":  [0, 0, 1, 1, 1, 0],
    "SW21": [0, 0, 0, 0, 0, 0, 0, 0],
    "SW22": [0, 0, 0, 0],
}

# Bank ordering and position counts (used by PDF renderer and validators)
SWITCH_BANKS: list[tuple[str, int]] = [
    ("SW1", 10), ("SW2", 6), ("SW3", 10), ("SW4", 6), ("SW21", 8), ("SW22", 4),
]


# ---------------------------------------------------------------------------
# AH001 (R-410A) lookup tables
#
# Capacity table is identical to AH002 today; duplicated here so the two
# refrigerants can diverge independently in future without coupling.
# ---------------------------------------------------------------------------

CAPACITY_OPTIONS_AH001: list[dict] = [
    {"value":  0, "label": "--- LEV Kit Size ---", "btuh":      0, "lev": "--- Not Selected ---", "sw2": [0, 0, 0, 0, 0, 0]},
    {"value":  1, "label": "6 MBH",                "btuh":   6000, "lev": "PAC-LV24AC-1",          "sw2": [0, 0, 1, 0, 0, 0]},
    {"value":  2, "label": "8 MBH",                "btuh":   8000, "lev": "PAC-LV24AC-1",          "sw2": [1, 0, 1, 0, 0, 0]},
    {"value":  3, "label": "12 MBH",               "btuh":  12000, "lev": "PAC-LV24AC-1",          "sw2": [0, 1, 1, 0, 0, 0]},
    {"value":  4, "label": "15 MBH",               "btuh":  15000, "lev": "PAC-LV24AC-1",          "sw2": [0, 0, 0, 1, 0, 0]},
    {"value":  5, "label": "18 MBH",               "btuh":  18000, "lev": "PAC-LV24AC-1",          "sw2": [0, 1, 0, 1, 0, 0]},
    {"value":  6, "label": "24 MBH",               "btuh":  24000, "lev": "PAC-LV24AC-1",          "sw2": [1, 0, 1, 1, 0, 0]},
    {"value":  7, "label": "27 MBH",               "btuh":  27000, "lev": "PAC-LV48AC-1",          "sw2": [0, 1, 1, 1, 0, 0]},
    {"value":  8, "label": "30 MBH",               "btuh":  30000, "lev": "PAC-LV48AC-1",          "sw2": [0, 0, 0, 0, 1, 0]},
    {"value":  9, "label": "36 MBH",               "btuh":  36000, "lev": "PAC-LV48AC-1",          "sw2": [0, 0, 1, 0, 1, 0]},
    {"value": 10, "label": "48 MBH",               "btuh":  48000, "lev": "PAC-LV48AC-1",          "sw2": [1, 0, 0, 1, 1, 0]},
    {"value": 11, "label": "54 MBH",               "btuh":  54000, "lev": "PAC-LV60AC-1",          "sw2": [0, 0, 1, 1, 1, 0]},
    {"value": 12, "label": "60 MBH",               "btuh":  60000, "lev": "PAC-LV60AC-1",          "sw2": [1, 1, 1, 1, 1, 0]},
    {"value": 13, "label": "72 MBH",               "btuh":  72000, "lev": "PAC-LV96AC-1",          "sw2": [0, 0, 0, 1, 0, 1]},
    {"value": 14, "label": "96 MBH",               "btuh":  96000, "lev": "PAC-LV96AC-1",          "sw2": [0, 1, 0, 0, 1, 1]},
    {"value": 15, "label": "120 MBH",              "btuh": 120000, "lev": "PAC-LV120AC-1",         "sw2": [0, 0, 1, 1, 1, 1]},
    {"value": 16, "label": "144 MBH",              "btuh": 144000, "lev": "PAC-LV96AC-1 (x2)",     "sw2": [0, 0, 0, 0, 1, 0]},
    {"value": 17, "label": "168 MBH",              "btuh": 168000, "lev": "PAC-LV96AC-1 (x2)",     "sw2": [0, 1, 0, 1, 1, 0]},
    {"value": 18, "label": "192 MBH",              "btuh": 192000, "lev": "PAC-LV96AC-1 (x2)",     "sw2": [0, 0, 1, 0, 0, 1]},
    {"value": 19, "label": "216 MBH",              "btuh": 216000, "lev": "PAC-LV120AC-1 (x2)",    "sw2": [0, 1, 1, 1, 0, 1]},
    {"value": 20, "label": "240 MBH",              "btuh": 240000, "lev": "PAC-LV120AC-1 (x2)",    "sw2": [0, 0, 0, 1, 1, 1]},
]

# AH001 only has three thermo-off options (no 82°F option, which is AH002-specific)
THERMO_OPTIONS_AH001: list[dict] = [
    {"value": 4, "label": "Thermo OFF at 59°F (Default)", "sw3": [1, 1], "sw4": [1, 1]},
    {"value": 3, "label": "Thermo OFF at 70°F",           "sw3": [0, 0], "sw4": [0, 0]},
    {"value": 1, "label": "Thermo OFF at 50°F",           "sw3": [0, 1], "sw4": [0, 1]},
]

# AH001 DAT setpoint range options (encoded via SW3[0])
DAT_SETPOINT_OPTIONS_AH001: list[dict] = [
    {"value": 1, "label": "Minimum 46°F / Maximum 82°F (Default)"},
    {"value": 2, "label": "Minimum 46°F / Maximum 95°F"},
]

DEFAULT_SWITCHES_AH001: dict[str, list[int]] = {
    "SW1": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0],
    "SW2": [0, 0, 0, 0, 0, 0],
    "SW3": [0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    "SW4": [1, 0, 0, 0, 0, 0, 0, 0, 1, 1],
    "SWA": [0, 0, 0],
    "SW5": [0],
}

# AH001 bank ordering — SW4 is 10 positions here (not 6 like AH002), SWA is a
# 3-position horizontal selector, SW5 is a 2-position horizontal voltage toggle
# rendered as a 1-bit array (0 = right cell active = 208V, 1 = left cell = 230V).
SWITCH_BANKS_AH001: list[tuple[str, int]] = [
    ("SW1", 10), ("SW2", 6), ("SW3", 10), ("SW4", 10), ("SWA", 3), ("SW5", 1),
]


# ---------------------------------------------------------------------------
# Per-unit switch generation (verbatim port of generateSwitchPositions, v4.6)
# ---------------------------------------------------------------------------

def _capacity_by_value(value: int, controller_type: str = CONTROLLER_AH002) -> dict:
    table = CAPACITY_OPTIONS_AH001 if controller_type == CONTROLLER_AH001 else CAPACITY_OPTIONS
    for opt in table:
        if opt["value"] == value:
            return opt
    raise ValueError(f"Unknown capacity value: {value} (controller={controller_type})")


def _thermo_by_value(value: int, controller_type: str = CONTROLLER_AH002) -> dict:
    table = THERMO_OPTIONS_AH001 if controller_type == CONTROLLER_AH001 else THERMO_OPTIONS
    for opt in table:
        if opt["value"] == value:
            return opt
    raise ValueError(f"Unknown thermo value: {value} (controller={controller_type})")


def generate_switch_positions(config: dict) -> dict:
    """
    Compute final DIP switch positions and CNRM connection state for a single unit.

    Dispatches on config["controller_type"]: defaults to PAC-AH002 for back-compat.

    Returns: {"switches": {"SW1": [...], ...}, "cnrm_connected": bool}
    """
    controller_type = config.get("controller_type", CONTROLLER_AH002)
    if controller_type == CONTROLLER_AH001:
        return _generate_switch_positions_ah001(config)
    return _generate_switch_positions_ah002(config)


def _generate_switch_positions_ah002(config: dict) -> dict:
    """
    AH002 (R-32) per-unit switch math. config keys (all required unless noted):
      capacity            int   index into CAPACITY_OPTIONS (1..20)
      control_mode        str   "discharge" (DAT) or "return" (RAT)
      heat_pump           bool  True for heat pump, False for cool only
      input_voltage       str   "208" or "230"
      discharge_enable    str   "central" or "bas"   (DAT only, ignored otherwise)
      discharge_setpoint  str   "central" or "bas"   (DAT only)
      thermo_temp         int   1..4 from THERMO_OPTIONS  (DAT only; 0 = leave default)
      dat_setpoint        int   1 or 2 from HEATING_SETPOINT_OPTIONS (DAT only)
      return_control      str   "room" or "rat"      (RAT only)
      return_enable       str   "central" or "bas"   (RAT only)
      temp_adjustment     bool  DAT BAS setpoint OR RAT stratification offset
    """
    capacity           = config["capacity"]
    control_mode       = config["control_mode"]
    heat_pump          = config["heat_pump"]
    input_voltage      = str(config["input_voltage"])
    discharge_enable   = config.get("discharge_enable", "central")
    discharge_setpoint = config.get("discharge_setpoint", "central")
    thermo_temp        = config.get("thermo_temp", 0)
    dat_setpoint       = config.get("dat_setpoint", 2)
    return_control     = config.get("return_control", "room")
    return_enable      = config.get("return_enable", "central")
    temp_adjustment    = config.get("temp_adjustment", False)

    switches = {bank: list(values) for bank, values in DEFAULT_SWITCHES.items()}
    e11 = 1 if control_mode == "return" else 0

    # SW1-1: RAT mode + room-temp control
    if e11 == 1 and return_control == "room":
        switches["SW1"][0] = 1

    # SW2: capacity bit pattern
    switches["SW2"] = list(_capacity_by_value(capacity)["sw2"])

    # SW3-1: Cooling only
    if not heat_pump:
        switches["SW3"][0] = 1

    # SW3-10: DAT upper limit 82 deg F (default 95 = position ON)
    if dat_setpoint == 1:
        switches["SW3"][9] = 0

    # SW3-2: RAT mode
    if e11 == 1:
        switches["SW3"][1] = 1

    # SW3-3: enable method
    if e11 == 1 or (e11 == 0 and discharge_enable == "bas"):
        switches["SW3"][2] = 1

    # SW3-4: temp adjustment / stratification
    if (e11 == 0 and discharge_enable == "bas") or (e11 == 1 and temp_adjustment):
        switches["SW3"][3] = 1

    # SW3-6: dual LEV when capacity index >= 16
    if capacity >= 16:
        switches["SW3"][5] = 1

    # SW3-8 / SW3-9: DAT thermo-off encoding
    if e11 == 0 and thermo_temp > 0:
        opt = _thermo_by_value(thermo_temp)
        switches["SW3"][7] = opt["sw3"][0]
        switches["SW3"][8] = opt["sw3"][1]

    # SW3-8 OFF when RAT stratification offset enabled
    if e11 == 1 and temp_adjustment:
        switches["SW3"][7] = 0

    # SW21-1, SW21-2
    if discharge_enable == "bas" and discharge_setpoint == "bas" and e11 == 0:
        switches["SW21"][0] = 0
        switches["SW21"][1] = 0
    else:
        switches["SW21"][0] = 0
        switches["SW21"][1] = 1

    # SW21-3, SW21-4: control mode
    if e11 == 0:
        switches["SW21"][2] = 1
        switches["SW21"][3] = 1
    else:
        switches["SW21"][2] = 0
        switches["SW21"][3] = 0

    # SW21-5: OFF
    switches["SW21"][4] = 0

    # SW21-6: 208V => ON, 230V => OFF
    switches["SW21"][5] = 1 if input_voltage == "208" else 0

    # SW21-7, SW21-8: OFF
    switches["SW21"][6] = 0
    switches["SW21"][7] = 0

    # CNRM jumper logic — connected when BAS provides the enable signal,
    # disconnected when Mitsubishi controls handle it internally.
    cnrm_connected = False
    if control_mode == "discharge":
        if discharge_enable == "bas" or discharge_setpoint == "bas":
            cnrm_connected = True
    elif control_mode == "return":
        if return_enable == "bas":
            cnrm_connected = True

    return {"switches": switches, "cnrm_connected": cnrm_connected}


def _generate_switch_positions_ah001(config: dict) -> dict:
    """
    AH001 (R-410A) per-unit switch math. Ported from the React reference
    `generateCompleteConfig()` (pac-ah001-configurator.html L435-502), plus
    the user-added SW5 voltage toggle (left=230V, right=208V).

    config keys (with sensible defaults applied if missing):
      capacity              int  index into CAPACITY_OPTIONS_AH001 (1..20)
      control_mode          str  "discharge" or "return"
      heat_pump             bool True for heat pump, False for cool only
      input_voltage         str  "208" or "230"
      discharge_enable      str  "central" or "bas"
      discharge_setpoint    str  "central" or "bas"
      thermo_temp           int  1, 3, or 4 from THERMO_OPTIONS_AH001 (DAT only)
      dat_setpoint          int  1 or 2 from DAT_SETPOINT_OPTIONS_AH001 (DAT only)
      return_control        str  "room" or "rat"
      return_enable         str  "central" or "bas"
      temp_adjustment       bool RAT stratification offset
      fan_controlled_by     str  "lev" or "bas"   (gates the extras below)
      run_fan_defrost       bool DAT-only extra
      electric_heat         bool RAT-only extra
      use_defrost_error     bool only when electric_heat=True
      humidifier_installed  bool RAT-only extra
      run_humidifier        bool only when humidifier_installed=True
    """
    capacity           = config["capacity"]
    control_mode       = config["control_mode"]
    heat_pump          = config["heat_pump"]
    input_voltage      = str(config["input_voltage"])
    discharge_enable   = config.get("discharge_enable", "central")
    discharge_setpoint = config.get("discharge_setpoint", "central")
    thermo_temp        = config.get("thermo_temp", 4)        # AH001 default = 59°F
    dat_setpoint       = config.get("dat_setpoint", 1)       # AH001 default = 82°F upper
    return_control     = config.get("return_control", "rat")
    return_enable      = config.get("return_enable", "central")
    temp_adjustment    = config.get("temp_adjustment", False)
    electric_heat      = config.get("electric_heat", False)
    humidifier_installed = config.get("humidifier_installed", False)
    run_humidifier     = config.get("run_humidifier", False)

    switches = {bank: list(values) for bank, values in DEFAULT_SWITCHES_AH001.items()}
    e11 = 1 if control_mode == "return" else 0

    # SW2: capacity bit pattern (then layered with cool-only and electric-heat flags)
    switches["SW2"] = list(_capacity_by_value(capacity, CONTROLLER_AH001)["sw2"])

    # SW2[1]: cool-only flag
    if not heat_pump:
        switches["SW2"][1] = 1

    # SW2[2]: electric heat installed (RAT-only per spec, but bit is written
    # literally from input — gating belongs to the UI layer)
    if electric_heat:
        switches["SW2"][2] = 1

    # SW1[5]: run humidifier during heating thermo-off (only meaningful when
    # humidifier installed AND user opted in; both must be true)
    if e11 == 1 and humidifier_installed and run_humidifier:
        switches["SW1"][5] = 1

    # SW3[0]: DAT setpoint upper limit — 0=82°F (default), 1=95°F
    if dat_setpoint == 2:
        switches["SW3"][0] = 1

    # SW3[1]: RAT mode flag
    if e11 == 1:
        switches["SW3"][1] = 1

    # SW3[2]: enable method (RAT always, or DAT with BAS enable)
    if e11 == 1 or (e11 == 0 and discharge_enable == "bas"):
        switches["SW3"][2] = 1

    # SW3[3]: temp adjustment / stratification logic
    if (e11 == 0 and discharge_enable == "bas") or (e11 == 1 and temp_adjustment):
        switches["SW3"][3] = 1

    # SW3[5]: dual LEV when capacity index >= 16
    if capacity >= 16:
        switches["SW3"][5] = 1

    # SW3[7..8] and SW4[6..7]: thermo-off pair (DAT only)
    if e11 == 0 and thermo_temp > 0:
        opt = _thermo_by_value(thermo_temp, CONTROLLER_AH001)
        switches["SW3"][7] = opt["sw3"][0]
        switches["SW3"][8] = opt["sw3"][1]
        switches["SW4"][6] = opt["sw4"][0]
        switches["SW4"][7] = opt["sw4"][1]
    elif e11 == 1 and temp_adjustment:
        switches["SW3"][7] = 1

    # SWA position (3-position horizontal selector):
    #   SWA[0]=1 → position 1 (right cell) — return mode OR discharge w/ central enable
    #   SWA[1]=1 → position 2 (middle)     — discharge with BAS enable AND BAS setpoint
    #   SWA[2]   → position 3 (left cell)  — not used by current algorithm
    if e11 == 1:
        switches["SWA"][0] = 1
    else:
        if discharge_enable == "bas" and discharge_setpoint == "bas":
            switches["SWA"][1] = 1
        else:
            switches["SWA"][0] = 1

    # SW5: voltage toggle — 0 = right cell active = 208V, 1 = left cell = 230V
    switches["SW5"][0] = 1 if input_voltage == "230" else 0

    # CNRM jumper logic (same shape as AH002) — connected when BAS provides
    # the enable signal, disconnected when Mitsubishi controls handle it.
    cnrm_connected = False
    if control_mode == "discharge":
        if discharge_enable == "bas" or discharge_setpoint == "bas":
            cnrm_connected = True
    elif control_mode == "return":
        if return_enable == "bas":
            cnrm_connected = True

    return {"switches": switches, "cnrm_connected": cnrm_connected}


# ---------------------------------------------------------------------------
# .dsbx parsing
# ---------------------------------------------------------------------------

@dataclass
class ParsedUnit:
    tag: str
    mnet: int | None
    btuh: int
    capacity_index: int           # index into the controller's CAPACITY_OPTIONS table
    capacity_label: str
    lev_assembly: str
    control_mode: str             # "discharge" | "return"
    raw_application_option: str
    controller_type: str          # CONTROLLER_AH001 or CONTROLLER_AH002

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "mnet": self.mnet,
            "btuh": self.btuh,
            "capacity_index": self.capacity_index,
            "capacity_label": self.capacity_label,
            "lev_assembly": self.lev_assembly,
            "control_mode": self.control_mode,
            "raw_application_option": self.raw_application_option,
            "controller_type": self.controller_type,
        }


_BTUH_RE = re.compile(r"(\d+)\s*Btu\s*/\s*h", re.IGNORECASE)


def _capacity_index_for_btuh(btuh: int, controller_type: str = CONTROLLER_AH002) -> int | None:
    table = CAPACITY_OPTIONS_AH001 if controller_type == CONTROLLER_AH001 else CAPACITY_OPTIONS
    for opt in table:
        if opt["btuh"] and opt["btuh"] == btuh:
            return opt["value"]
    return None


def _control_mode_from_application(opt: str) -> str:
    """Map dsbx LEVApplicationOption to v4.6 controlMode string."""
    if opt == "Ventilation":
        return "discharge"   # DAT default for ventilation/DOAS
    if opt == "RoomAirConditioning":
        return "return"      # RAT default for indoor space conditioning
    return "discharge"       # safe fallback


def parse_dsbx(file_bytes: bytes) -> dict:
    """
    Parse a .dsbx file (ZIP-wrapped XML) and extract LEV Kits.

    Both R-32 (PAC-AH002) and R-410A (PAC-AH001) kits are now extracted; each
    unit is tagged with its controller_type. Refrigerant is detected by the
    "(r32)" substring in the ModelNumber field.

    Returns: {
      "project_name":      str,
      "units":             [ParsedUnit.to_dict, ...],
      "controllers_found": {CONTROLLER_AH001: int, CONTROLLER_AH002: int},
      "skipped_r410a":     [],            # retained for back-compat, now always empty
      "warnings":          [str, ...]
    }
    """
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            names = zf.namelist()
            if "xml" not in names:
                raise ValueError(
                    f".dsbx archive missing 'xml' member (found: {names})"
                )
            xml_bytes = zf.read("xml")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid .dsbx archive: {exc}") from exc

    root = ET.fromstring(xml_bytes.decode("utf-8-sig"))

    project_name_raw = (root.findtext("ProjectName") or "LEV Config").strip()
    if project_name_raw.lower().endswith(".dsbx"):
        project_name = project_name_raw[:-5].strip()
    else:
        project_name = project_name_raw
    if not project_name:
        project_name = "LEV Config"

    units: list[dict] = []
    warnings: list[str] = []
    controllers_found = {CONTROLLER_AH001: 0, CONTROLLER_AH002: 0}

    for idu in root.iter("IndoorUnit"):
        model = (idu.findtext("ModelNumber") or "").strip()
        if "lev kit" not in model.lower():
            continue                                                # FCU - ignore

        tag = (idu.findtext("ReferenceTag") or "").strip()
        application = (idu.findtext("LEVApplicationOption") or "").strip()
        mnet_raw = idu.findtext("MNetAddress")
        try:
            mnet = int(mnet_raw) if mnet_raw is not None else None
        except ValueError:
            mnet = None

        # R-32 model strings include "(R32)"; absence means R-410A (PAC-AH001).
        is_r32 = "(r32)" in model.lower()
        controller_type = CONTROLLER_AH002 if is_r32 else CONTROLLER_AH001

        # Capacity from leading "<n> Btu/h" - must exact-match a known size
        m = _BTUH_RE.search(model)
        if not m:
            warnings.append(
                f"Could not parse capacity from model '{model}' (tag '{tag}'). Skipped."
            )
            continue
        btuh = int(m.group(1))
        cap_idx = _capacity_index_for_btuh(btuh, controller_type)
        if cap_idx is None:
            warnings.append(
                f"Capacity {btuh} Btu/h (tag '{tag}') is not a recognized LEV Kit size. Skipped."
            )
            continue

        control_mode = _control_mode_from_application(application)
        if application not in ("Ventilation", "RoomAirConditioning"):
            warnings.append(
                f"Tag '{tag}': unexpected LEVApplicationOption '{application}'. "
                f"Defaulted to Discharge Temp control."
            )

        cap_opt = _capacity_by_value(cap_idx, controller_type)
        controllers_found[controller_type] += 1
        units.append(
            ParsedUnit(
                tag=tag or f"Unit-{mnet or '?'}",
                mnet=mnet,
                btuh=btuh,
                capacity_index=cap_idx,
                capacity_label=cap_opt["label"],
                lev_assembly=cap_opt["lev"],
                control_mode=control_mode,
                raw_application_option=application,
                controller_type=controller_type,
            ).to_dict()
        )

    # Stable sort: AH002 (R-32) units first, then AH001 (R-410A) — within each
    # controller group, by M-Net address if present, else by tag. This matches
    # the desired PDF page ordering downstream.
    def _sort_key(u: dict) -> tuple:
        ctrl_rank = 0 if u["controller_type"] == CONTROLLER_AH002 else 1
        return (ctrl_rank, u["mnet"] is None, u["mnet"] or 0, u["tag"])

    units.sort(key=_sort_key)

    return {
        "project_name":      project_name,
        "units":             units,
        "controllers_found": controllers_found,
        "skipped_r410a":     [],
        "warnings":          warnings,
    }


# ---------------------------------------------------------------------------
# Per-unit record assembly (turn parsed unit + user choices into a PDF row)
# ---------------------------------------------------------------------------

def thermistor_wiring(control_mode: str) -> tuple[str, str]:
    """Return (TH21_Air, TH24_Air) labels for the given control mode."""
    if control_mode == "discharge":
        return ("Discharge Sensor", "Inlet Sensor")
    return ("Inlet Sensor", "Discharge Sensor")


def control_mode_display(unit: dict) -> str:
    """Human-readable Control Mode column value."""
    if unit["control_mode"] == "discharge":
        return "Discharge Temperature"
    if unit.get("return_control") == "room":
        return "Room Temperature"
    return "Return Temperature"


def _enable_text(unit_cfg: dict) -> str:
    """Short label for the PDF's Enable Type column (AH001 only)."""
    if unit_cfg["control_mode"] == "discharge":
        return "BAS Dry Contact" if unit_cfg["discharge_enable"] == "bas" else "Central Controller"
    return "BAS Dry Contact" if unit_cfg["return_enable"] == "bas" else "Central Controller"


def _setpoint_text(unit_cfg: dict) -> str:
    """Short label for the PDF's Setpoint Type column (AH001 only)."""
    if unit_cfg["control_mode"] == "discharge":
        return "0-10VDC from BAS" if unit_cfg["discharge_setpoint"] == "bas" else "Central Controller"
    return "Return Air Sensor" if unit_cfg["return_control"] == "rat" else "Room Temp Remote"


def build_unit_record(parsed: dict, **overrides: Any) -> dict:
    """
    Combine a parsed dsbx unit (or a manually-entered unit) with user overrides
    into the canonical record consumed by the PDF renderer.

    Controller type is taken from `parsed["controller_type"]` (or overrides),
    defaulting to PAC-AH002 when absent so legacy callers still work.

    For AH001 units, the extra inputs (fan_controlled_by, run_fan_defrost,
    electric_heat, use_defrost_error, humidifier_installed, run_humidifier)
    are accepted via overrides; defaults are safe (LEV-controlled, all-False).
    """
    controller_type = overrides.get(
        "controller_type",
        parsed.get("controller_type", CONTROLLER_AH002),
    )
    is_ah001 = controller_type == CONTROLLER_AH001

    config = {
        "controller_type":    controller_type,
        "capacity":           parsed["capacity_index"],
        "control_mode":       overrides.get("control_mode", parsed["control_mode"]),
        "heat_pump":          overrides.get("heat_pump", True),
        "input_voltage":      overrides.get("input_voltage", "208"),
        "discharge_enable":   overrides.get("discharge_enable",   "central"),
        "discharge_setpoint": overrides.get("discharge_setpoint", "central"),
        # AH001 defaults differ from AH002: thermo 59°F (value 4), dat 82°F (value 1)
        "thermo_temp":        overrides.get("thermo_temp",        4 if is_ah001 else 2),
        "dat_setpoint":       overrides.get("dat_setpoint",       1 if is_ah001 else 2),
        "return_control":     overrides.get("return_control",     "room"),
        "return_enable":      overrides.get("return_enable",      "central"),
        "temp_adjustment":    overrides.get("temp_adjustment",    False),
    }
    if is_ah001:
        config.update({
            "fan_controlled_by":    overrides.get("fan_controlled_by", "bas"),
            "run_fan_defrost":      overrides.get("run_fan_defrost", False),
            "electric_heat":        overrides.get("electric_heat", False),
            "use_defrost_error":    overrides.get("use_defrost_error", False),
            "humidifier_installed": overrides.get("humidifier_installed", False),
            "run_humidifier":       overrides.get("run_humidifier", False),
        })

    result = generate_switch_positions(config)
    cap_opt = _capacity_by_value(config["capacity"], controller_type)
    th21, th24 = thermistor_wiring(config["control_mode"])

    record = {
        "tag":              parsed["tag"],
        "mnet":             parsed.get("mnet"),
        "controller_type":  controller_type,
        "capacity_index":   config["capacity"],
        "capacity_label":   cap_opt["label"],
        "lev_assembly":     cap_opt["lev"],
        "control_mode":     config["control_mode"],
        "return_control":   config["return_control"],
        "heat_pump":        config["heat_pump"],
        "input_voltage":    config["input_voltage"],
        "discharge_enable":   config["discharge_enable"],
        "discharge_setpoint": config["discharge_setpoint"],
        "thermo_temp":        config["thermo_temp"],
        "dat_setpoint":       config["dat_setpoint"],
        "return_enable":      config["return_enable"],
        "temp_adjustment":    config["temp_adjustment"],
        "switches":           result["switches"],
        "cnrm_connected":     result["cnrm_connected"],
        "th21_air":           th21,
        "th24_air":           th24,
    }
    if is_ah001:
        record.update({
            "fan_controlled_by":    config["fan_controlled_by"],
            "run_fan_defrost":      config["run_fan_defrost"],
            "electric_heat":        config["electric_heat"],
            "use_defrost_error":    config["use_defrost_error"],
            "humidifier_installed": config["humidifier_installed"],
            "run_humidifier":       config["run_humidifier"],
            # Derived strings for the PDF (AH001 prints these inline in place of
            # the TH21A/TH24A thermistor labels used on AH002 pages).
            "enable_text":          _enable_text(config),
            "setpoint_text":        _setpoint_text(config),
        })
    return record


# ---------------------------------------------------------------------------
# Footnotes
# ---------------------------------------------------------------------------

def _unit_note_texts(u: dict) -> list[str]:
    """Per-unit list of note texts (excluding the always-present legend).

    Only non-default settings produce a note. Units sharing the same setting
    will share the same note text, which `compute_footnotes` then dedupes
    into a single numbered note.

    AH001 units omit enable/setpoint notes — that info is rendered inline on
    the AH001 PDF page (replacing the TH21A/TH24A thermistor slots).
    """
    texts: list[str] = []
    cm = u["control_mode"]
    controller_type = u.get("controller_type", CONTROLLER_AH002)
    is_ah001 = controller_type == CONTROLLER_AH001

    if not u["heat_pump"]:
        texts.append("Cool-only operation (heat pump function disabled)")

    if cm == "discharge":
        if not is_ah001:
            if u["discharge_enable"] == "bas":
                texts.append("Enable via dry contact from BAS")
            if u["discharge_setpoint"] == "bas":
                texts.append("Setpoint via 0-10V signal from BAS")
        # Thermo-off note: defaults differ between controllers (AH002=value 2,
        # AH001=value 4); only flag when the user picked a non-default.
        default_thermo = 4 if is_ah001 else 2
        if u["thermo_temp"] != default_thermo:
            lbl = _thermo_by_value(u["thermo_temp"], controller_type)["label"].replace(" (Default)", "")
            texts.append(lbl)
        # DAT setpoint scaling note — AH001 default is 82°F, AH002 default is 95°F
        if is_ah001:
            if u["dat_setpoint"] == 2:
                texts.append("DAT Setpoint Scaling: 1.0V = 46°F, 9.6V = 95°F upper limit")
                texts.append("DAT upper limit set to 95°F (default is 82°F)")
            else:
                texts.append("DAT Setpoint Scaling: 1.0V = 46°F, 7.4V = 82°F upper limit")
        else:
            if u["dat_setpoint"] == 2:
                texts.append("DAT Setpoint Scaling: 1.0V = 46°F, 9.6V = 95°F upper limit")
            else:
                texts.append("DAT Setpoint Scaling: 1.0V = 46°F, 7.4V = 82°F upper limit")
                texts.append("DAT upper limit set to 82°F (default is 95°F)")
    else:
        if not is_ah001:
            if u["return_enable"] == "bas":
                texts.append("Enable via dry contact from BAS")
            if u["return_control"] == "rat":
                texts.append("Setpoint by return air sensor (TH24)")
        if u["temp_adjustment"]:
            texts.append("Return air stratification offset enabled")

    # AH001-specific extras
    if is_ah001:
        if u.get("electric_heat") and cm == "return":
            texts.append("Electric heat installed")
            if u.get("use_defrost_error"):
                texts.append("Electric heat operates during defrost and error states")
        if u.get("humidifier_installed") and cm == "return":
            texts.append("Humidifier installed")
            if u.get("run_humidifier"):
                texts.append("Humidifier runs during heating thermo-off")
        if u.get("run_fan_defrost") and cm == "discharge":
            texts.append("Fan runs during defrost")
        if u.get("fan_controlled_by") == "bas":
            texts.append("AHU/FCU fan controlled by BAS")

    return texts


def compute_footnotes(units: list[dict]) -> tuple[list[str], dict[str, list[int]]]:
    """
    Build the Notes section and per-unit footnote references.

    Numbering scheme:
      1..N. Distinct non-default settings across units, in the order they
            first appear. Units sharing a setting share its number, so the
            Notes column compactly lists exactly which non-default options
            apply to each unit.

    The switch-position visual legend is rendered separately by the PDF
    renderer (above the Notes section, not as a numbered footnote).

    Returns:
      (footnote_lines, per_unit_refs)
        footnote_lines : ordered text lines including the "n." prefix
        per_unit_refs  : {unit_tag: [footnote_number, ...]}
    """
    per_unit_texts = {u["tag"]: _unit_note_texts(u) for u in units}

    text_to_num: dict[str, int] = {}
    ordered_texts: list[str] = []
    for u in units:
        for t in per_unit_texts[u["tag"]]:
            if t not in text_to_num:
                text_to_num[t] = len(text_to_num) + 1
                ordered_texts.append(t)

    lines: list[str] = []
    for t in ordered_texts:
        lines.append(f"{text_to_num[t]}. {t}")

    refs: dict[str, list[int]] = {}
    for u in units:
        refs[u["tag"]] = [text_to_num[t] for t in per_unit_texts[u["tag"]]]

    return lines, refs


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def render_submittal_pdf(
    units:                  list[dict],
    project_name:           str,
    voltage:                str = "208",
    layout:                 str = "horizontal",
    refrigerant_selection:  str = "ah002",
) -> bytes:
    """
    Render the LEV Kit submittal PDF.

    units:                 list of records produced by build_unit_record();
                           each record carries a controller_type field
    project_name:          shown in title and used in filename
    voltage:               "208" or "230" - shown in the header subline
    layout:                "horizontal" (units down rows) or "vertical"
                           (units across columns)
    refrigerant_selection: "ah001" | "ah002" | "both" — used to decide whether
                           to emit page breaks between controller groups even
                           when a chunk is empty. Defaults to "ah002" for
                           legacy callers.

    The renderer partitions units into AH002 (R-32) and AH001 (R-410A) groups
    and emits one page block per group with controller-specific column layout:
      - AH002 pages render SW21 + SW22 + TH21A/TH24A thermistor labels
      - AH001 pages render SWA (3-position selector) + SW5 (2-cell voltage
        toggle) + inline Enable Type / Setpoint Type text in place of the
        thermistor cells, and omit enable/setpoint footnotes
    AH002 pages always come first.
    """
    _ = refrigerant_selection  # currently unused; reserved for future hints
    # Imported lazily so this module remains importable without reportlab during
    # parse-only tests.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether,
        PageBreak,
    )

    # --- DIP switch flowable -------------------------------------------------
    from reportlab.platypus import Flowable

    class DipSwitchBank(Flowable):
        """Vector DIP switch bank styled to match real PAC-AH002 hardware.

        Each switch position is drawn as its own bounding box (per the v4.6
        anatomy diagram):
          * Position #1 draws a full rectangle (4 sides).
          * Positions #2..n draw only top + right + bottom — they share the
            left edge with the previous position's right edge, so adjacent
            slots butt cleanly without doubling the line weight.
          * Inside each box, two cells (top=ON, bottom=OFF) sit inset on
            every side by INSET, including the mid-gap between cells, so
            whitespace is consistent in all directions.
        """
        CELL_W    = 6        # painted cell width
        CELL_H    = 12       # painted cell height
        INSET     = 2.0      # whitespace in every direction (top/bottom/left/right/mid)
        FRAME_LW  = 1.5      # outer/per-switch box stroke
        INNER_LW  = 0.4      # cell-border stroke
        LABEL_W   = 14       # left margin reserved for ON/OFF text
        POS_GAP   = 2        # gap between frame bottom and position numbers
        FONT      = "Helvetica"
        FONT_SZ   = 6

        def __init__(self, label: str, values: list[int], show_label: bool = True):
            super().__init__()
            self.label = label
            self.values = values
            self.show_label = show_label
            self.n = len(values)
            self.slot_w = self.CELL_W + 2 * self.INSET
            self.slot_h = 2 * self.CELL_H + 3 * self.INSET   # top + cell + mid + cell + bottom
            self.width = self.LABEL_W + self.n * self.slot_w
            label_h = (self.FONT_SZ + 2) if show_label else 0
            self.height = (self.FONT_SZ + 2 + self.POS_GAP
                           + self.slot_h + label_h)

        def draw(self):
            c = self.canv
            c.setFont(self.FONT, self.FONT_SZ)

            # Position numbers at the bottom
            y = 0
            for i in range(self.n):
                cx = self.LABEL_W + (i + 0.5) * self.slot_w
                c.drawCentredString(cx, y, str(i + 1))
            y += self.FONT_SZ + 2 + self.POS_GAP

            fx = self.LABEL_W
            fy = y

            # ON / OFF labels at the left, centered on each cell's vertical midline
            on_text_y  = fy + 2 * self.INSET + self.CELL_H + self.CELL_H / 2 - self.FONT_SZ / 2 + 1
            off_text_y = fy +     self.INSET                + self.CELL_H / 2 - self.FONT_SZ / 2 + 1
            c.drawRightString(self.LABEL_W - 2, on_text_y,  "ON")
            c.drawRightString(self.LABEL_W - 2, off_text_y, "OFF")

            c.setStrokeColor(colors.black)

            for i, v in enumerate(self.values):
                sx = fx + i * self.slot_w

                # Per-switch bounding box — full rect on switch 0, then only
                # top/right/bottom on subsequent switches so the shared edge
                # with the previous switch isn't double-drawn.
                c.setLineWidth(self.FRAME_LW)
                if i == 0:
                    c.rect(sx, fy, self.slot_w, self.slot_h, stroke=1, fill=0)
                else:
                    c.line(sx,                   fy + self.slot_h, sx + self.slot_w, fy + self.slot_h)
                    c.line(sx + self.slot_w,     fy,               sx + self.slot_w, fy + self.slot_h)
                    c.line(sx,                   fy,               sx + self.slot_w, fy)

                # Inner cells: thin border, black fill on the active side
                c.setLineWidth(self.INNER_LW)
                cell_x = sx + self.INSET
                on_cell_y  = fy + 2 * self.INSET + self.CELL_H
                off_cell_y = fy +     self.INSET
                c.setFillColor(colors.black if v == 1 else colors.white)
                c.rect(cell_x, on_cell_y, self.CELL_W, self.CELL_H,
                       stroke=1, fill=1)
                c.setFillColor(colors.black if v == 0 else colors.white)
                c.rect(cell_x, off_cell_y, self.CELL_W, self.CELL_H,
                       stroke=1, fill=1)

            c.setFillColor(colors.black)
            c.setLineWidth(1)

            if self.show_label:
                c.setFont("Helvetica-Bold", 7)
                c.drawString(self.LABEL_W,
                             fy + self.slot_h + 2,
                             self.label)

    class SingleRowSwitchBank(Flowable):
        """Half-height single-row selector bank used by AH001 SWA and SW5.

        Renders like DipSwitchBank (same stroke widths, shared edges between
        adjacent cells, position labels below) but with only one cell per
        slot instead of a stacked ON/OFF pair. Used for:
          * SWA — 3-position horizontal rotary selector (labels 3, 2, 1)
          * SW5 — 2-cell voltage toggle (labels 230V, 208V)
        Caller supplies the cell labels and a per-cell values list — index 0
        means "cell unfilled (white)", 1 means "cell filled (black)".
        """
        CELL_W   = 6
        CELL_H   = 12
        INSET    = 2.0
        FRAME_LW = 1.5
        INNER_LW = 0.4
        POS_GAP  = 2
        FONT     = "Helvetica"
        FONT_SZ  = 6

        def __init__(self, label: str, cell_labels: list[str],
                     values: list[int], show_label: bool = True):
            super().__init__()
            self.label       = label
            self.cell_labels = cell_labels
            self.values      = values
            self.show_label  = show_label
            self.n           = len(values)
            # Cells always share edges (single continuous bordered bank). When
            # labels like "230V" / "208V" are wider than the default cell
            # width, the cell+inner-rect grow horizontally to fit — accepting
            # squarer (less narrow) cells. Labels are centered on their cell
            # but can overflow slightly into the gap-free space; user-confirmed
            # acceptable trade.
            max_lbl_chars = max((len(s) for s in cell_labels), default=1)
            min_cell_w_for_labels = max_lbl_chars * 3.6 + 1      # ~3.6pt per char @ size 6
            self.cell_w      = max(self.CELL_W, min_cell_w_for_labels)
            self.cell_box_w  = self.cell_w + 2 * self.INSET
            self.slot_h      = self.CELL_H + 2 * self.INSET
            self.width       = self.n * self.cell_box_w
            bank_lbl_h       = (self.FONT_SZ + 2) if show_label else 0
            self.height      = self.FONT_SZ + 2 + self.POS_GAP + self.slot_h + bank_lbl_h

        def draw(self):
            c = self.canv
            c.setFont(self.FONT, self.FONT_SZ)

            # Bottom row: position labels, centered on each cell's box
            y = 0
            for i, lbl in enumerate(self.cell_labels):
                cx = (i + 0.5) * self.cell_box_w
                c.drawCentredString(cx, y, lbl)
            y += self.FONT_SZ + 2 + self.POS_GAP

            fy = y
            c.setStrokeColor(colors.black)

            for i, v in enumerate(self.values):
                sx = i * self.cell_box_w

                # Shared-edge bordered bank: cell 0 draws full rect, cells 1+
                # draw only top/right/bottom so the bank reads as one
                # continuous bordered region (matches SWA.png reference).
                c.setLineWidth(self.FRAME_LW)
                if i == 0:
                    c.rect(sx, fy, self.cell_box_w, self.slot_h, stroke=1, fill=0)
                else:
                    c.line(sx,                    fy + self.slot_h,
                           sx + self.cell_box_w,  fy + self.slot_h)
                    c.line(sx + self.cell_box_w,  fy,
                           sx + self.cell_box_w,  fy + self.slot_h)
                    c.line(sx,                    fy,
                           sx + self.cell_box_w,  fy)

                c.setLineWidth(self.INNER_LW)
                cell_x = sx + self.INSET
                cell_y = fy + self.INSET
                c.setFillColor(colors.black if v == 1 else colors.white)
                c.rect(cell_x, cell_y, self.cell_w, self.CELL_H, stroke=1, fill=1)

            c.setFillColor(colors.black)
            c.setLineWidth(1)

            if self.show_label:
                c.setFont("Helvetica-Bold", 7)
                c.drawString(0, fy + self.slot_h + 2, self.label)

    # Helpers to map algorithm-produced switch arrays to the visual cell order
    # expected by SingleRowSwitchBank.
    def _swa_visual(values):
        # Algorithm writes SWA[0..2]; React reference renders cells left-to-right
        # as positions [3, 2, 1]. So algorithm index N maps to visual cell
        # (n_cells - 1 - N) and the cell-labels are ["3", "2", "1"].
        return list(reversed(values))

    def _sw5_visual(values):
        # SW5[0]=1 -> 230V (left cell active), 0 -> 208V (right cell active).
        bit = values[0] if values else 0
        return [1, 0] if bit == 1 else [0, 1]

    # --- Document setup ------------------------------------------------------
    # Tabloid landscape: 17 x 11 in. Both layouts use landscape — vertical
    # paginates across multiple pages when unit columns exceed page width.
    TABLOID = (17 * inch, 11 * inch)
    pagesize = landscape(TABLOID)
    margin = 0.4 * inch

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=pagesize,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin,  bottomMargin=margin,
        title=f"{project_name} - LEV Kit Configuration",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCenter", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=14, leading=16, alignment=1,
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9, alignment=1, spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontName="Helvetica", fontSize=8, leading=10, alignment=1,
    )
    notes_header = ParagraphStyle(
        "NotesHeader", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=10, spaceAfter=4,
    )
    notes_body_style = ParagraphStyle(
        "NotesBody", parent=styles["Normal"],
        fontName="Helvetica", fontSize=8, leading=10,
    )

    chunk_title_style = ParagraphStyle(
        "ChunkTitle", parent=styles["Title"],
        fontName="Helvetica-Bold", fontSize=12, leading=14, alignment=1,
        spaceAfter=8, spaceBefore=4,
    )

    # --- Header --------------------------------------------------------------
    story: list = [
        Paragraph("LEV Kit Configuration", title_style),
        Paragraph(
            f"{project_name} &middot; {date.today().isoformat()}",
            sub_style,
        ),
    ]

    # --- Partition units by controller; render each non-empty group ---------
    ah002_units = [u for u in units
                   if u.get("controller_type", CONTROLLER_AH002) == CONTROLLER_AH002]
    ah001_units = [u for u in units if u.get("controller_type") == CONTROLLER_AH001]
    groups: list[tuple[str, list[dict]]] = []
    if ah002_units:
        groups.append((CONTROLLER_AH002, ah002_units))
    if ah001_units:
        groups.append((CONTROLLER_AH001, ah001_units))
    # If a project has zero units at all (manual entry edge case), still emit
    # an empty AH002 page so the PDF isn't blank.
    if not groups:
        groups = [(CONTROLLER_AH002, [])]

    grey = colors.HexColor("#D3D3D3")

    for gi, (ctrl, group_units) in enumerate(groups):
        if gi > 0:
            story.append(PageBreak())

        is_ah001 = ctrl == CONTROLLER_AH001
        ref_lbl  = REFRIGERANT_LABEL[ctrl]
        story.append(Paragraph(
            f"LEV Kit Configuration &ndash; {ctrl} ({ref_lbl})",
            chunk_title_style,
        ))

        # Footnotes are computed per-group so numbering resets between
        # controllers (matches the "AH002 pages then AH001 pages" structure).
        footnote_lines, per_unit_refs = compute_footnotes(group_units)

        def _guide_note_flowables(footnote_lines=footnote_lines):
            lon  = DipSwitchBank("ON",  [1], show_label=False)
            loff = DipSwitchBank("OFF", [0], show_label=False)
            ltbl = Table(
                [[lon,  Paragraph("= Switch ON,",  body_style),
                  loff, Paragraph("= Switch OFF", body_style)]],
                colWidths=[lon.width + 6, 70, loff.width + 6, 70],
            )
            ltbl.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            ltbl.hAlign = "LEFT"
            result = [KeepTogether([Paragraph("Switch Position Guide", notes_header), ltbl])]
            if footnote_lines:
                result.append(Paragraph("Notes", notes_header))
                result += [Paragraph(ln, notes_body_style) for ln in footnote_lines]
            return result

        def _ref(unit):
            return ", ".join(str(n) for n in per_unit_refs.get(unit["tag"], []))

        if layout == "horizontal":
            # Controller-specific column-set selection. Both layouts keep 14
            # columns so the body table style spans line up; only the labels
            # and cell content differ.
            if is_ah001:
                header_top = [
                    "Unit Tag", "Capacity", "Control\nMode", "Required\nLEV",
                    "SW1", "SW2", "SW3", "SW4", "SWA", "SW5",
                    "Enable\nType", "Setpoint\nType",
                    "CNRM\nJumper", "Notes",
                ]
                header_sub = [""] * 14
                # AH001 col widths: SW4 grew 6→10 positions, SWA/SW5 narrower
                # than SW21/SW22, enable/setpoint text columns are wider than
                # the AH002 thermistor columns. Total ≈ 1145pt (same budget).
                col_widths = [
                    65, 60, 100, 85,
                    120, 80, 120, 120, 55, 55,
                    85, 85,
                    70, 50,
                ]
            else:
                header_top = [
                    "Unit Tag", "Capacity", "Control\nMode", "Required\nLEV",
                    "SW1", "SW2", "SW3", "SW4", "SW21", "SW22",
                    "Thermistor Wiring", "",
                    "CNRM\nJumper", "Notes",
                ]
                header_sub = [
                    "", "", "", "",
                    "", "", "", "", "", "",
                    "TH21\nAir", "TH24\nAir",
                    "", "",
                ]
                col_widths = [
                    65, 60, 100, 85,
                    120, 80, 120, 80, 100, 60,
                    75, 75,
                    70, 55,
                ]

            data_rows: list[list] = []
            for u in group_units:
                if is_ah001:
                    swa_visual = _swa_visual(u["switches"]["SWA"])
                    sw5_visual = _sw5_visual(u["switches"]["SW5"])
                    data_rows.append([
                        u["tag"],
                        u["capacity_label"],
                        Paragraph(control_mode_display(u).replace(" ", "<br/>", 1), body_style),
                        u["lev_assembly"],
                        DipSwitchBank("SW1", u["switches"]["SW1"], show_label=False),
                        DipSwitchBank("SW2", u["switches"]["SW2"], show_label=False),
                        DipSwitchBank("SW3", u["switches"]["SW3"], show_label=False),
                        DipSwitchBank("SW4", u["switches"]["SW4"], show_label=False),
                        SingleRowSwitchBank("SWA", ["3", "2", "1"], swa_visual, show_label=False),
                        SingleRowSwitchBank("SW5", ["230V", "208V"], sw5_visual, show_label=False),
                        Paragraph(u.get("enable_text", ""), body_style),
                        Paragraph(u.get("setpoint_text", ""), body_style),
                        "Connected" if u["cnrm_connected"] else "Disconnected",
                        _ref(u),
                    ])
                else:
                    data_rows.append([
                        u["tag"],
                        u["capacity_label"],
                        Paragraph(control_mode_display(u).replace(" ", "<br/>", 1), body_style),
                        u["lev_assembly"],
                        DipSwitchBank("SW1",  u["switches"]["SW1"],  show_label=False),
                        DipSwitchBank("SW2",  u["switches"]["SW2"],  show_label=False),
                        DipSwitchBank("SW3",  u["switches"]["SW3"],  show_label=False),
                        DipSwitchBank("SW4",  u["switches"]["SW4"],  show_label=False),
                        DipSwitchBank("SW21", u["switches"]["SW21"], show_label=False),
                        DipSwitchBank("SW22", u["switches"]["SW22"], show_label=False),
                        Paragraph(u["th21_air"].replace(" ", "<br/>", 1), body_style),
                        Paragraph(u["th24_air"].replace(" ", "<br/>", 1), body_style),
                        "Connected" if u["cnrm_connected"] else "Disconnected",
                        _ref(u),
                    ])

            ts_cmds = [
                ("BACKGROUND",   (0, 0), (-1, 1), grey),
                ("FONTNAME",     (0, 0), (-1, 1), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, 1), 8),
                ("ALIGN",        (0, 0), (-1, 1), "CENTER"),
                ("VALIGN",       (0, 0), (-1, 1), "MIDDLE"),
            ]
            # On AH002 pages, "Thermistor Wiring" spans columns 10-11 on the top
            # header row; AH001 pages have independent Enable/Setpoint columns
            # so no span is applied.
            if not is_ah001:
                ts_cmds.append(("SPAN", (10, 0), (11, 0)))
            # Each single-row header column spans both header rows (vertical merge).
            single_row_cols = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13]
            if is_ah001:
                # AH001 has 14 single-row header columns (the enable/setpoint
                # are independent, no spanning sub-header).
                single_row_cols = list(range(14))
            for c_idx in single_row_cols:
                ts_cmds.append(("SPAN", (c_idx, 0), (c_idx, 1)))
            ts_cmds += [
                ("FONTNAME",     (0, 2), (-1, -1), "Helvetica"),
                ("FONTSIZE",     (0, 2), (-1, -1), 8),
                ("ALIGN",        (0, 2), (-1, -1), "CENTER"),
                ("VALIGN",       (0, 2), (-1, -1), "MIDDLE"),
                ("FONTNAME",     (0, 2), (0, -1), "Helvetica-Bold"),
                ("GRID",         (0, 0), (-1, -1), 0.4, colors.black),
                ("LEFTPADDING",  (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING",   (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
            ]
            ts = TableStyle(ts_cmds)

            H_ROWS_PER_PAGE = 10
            h_chunks = (
                [data_rows[i:i + H_ROWS_PER_PAGE]
                 for i in range(0, len(data_rows), H_ROWS_PER_PAGE)]
                or [[]]
            )
            for ci, chunk_rows in enumerate(h_chunks):
                chunk_tbl = Table([header_top, header_sub] + chunk_rows, colWidths=col_widths)
                chunk_tbl.setStyle(ts)
                story.append(chunk_tbl)
                story.append(Spacer(1, 12))
                story.extend(_guide_note_flowables())
                if ci < len(h_chunks) - 1:
                    story.append(PageBreak())

        else:
            # Vertical: field labels down the left, one column per unit.
            banks = SWITCH_BANKS_AH001 if is_ah001 else SWITCH_BANKS
            n_units = len(group_units)
            label_col = 130
            min_unit_col = 120
            usable = pagesize[0] - 2 * margin - label_col
            units_per_page = max(1, int(usable // min_unit_col))

            v_chunks = (
                [group_units[i:i + units_per_page]
                 for i in range(0, n_units, units_per_page)]
                or [[]]
            )

            for chunk_idx, chunk in enumerate(v_chunks):
                chunk_n = len(chunk)
                unit_col = max(
                    min_unit_col,
                    usable // max(1, chunk_n) if chunk_n else min_unit_col,
                )

                rows: list[list] = []
                rows.append(["Unit Tag"] + [u["tag"] for u in chunk])
                rows.append(["Capacity"] + [u["capacity_label"] for u in chunk])
                rows.append(
                    ["Control Mode"]
                    + [Paragraph(control_mode_display(u), body_style) for u in chunk]
                )
                rows.append(["Required LEV"] + [u["lev_assembly"] for u in chunk])

                for bank, _n in banks:
                    if bank == "SWA":
                        rows.append([bank] + [
                            SingleRowSwitchBank(
                                bank, ["3", "2", "1"],
                                _swa_visual(u["switches"]["SWA"]),
                                show_label=False,
                            )
                            for u in chunk
                        ])
                    elif bank == "SW5":
                        rows.append([bank] + [
                            SingleRowSwitchBank(
                                bank, ["230V", "208V"],
                                _sw5_visual(u["switches"]["SW5"]),
                                show_label=False,
                            )
                            for u in chunk
                        ])
                    else:
                        rows.append([bank] + [
                            DipSwitchBank(bank, u["switches"][bank], False)
                            for u in chunk
                        ])

                if is_ah001:
                    rows.append(
                        ["Enable Type"]
                        + [Paragraph(u.get("enable_text", ""), body_style) for u in chunk]
                    )
                    rows.append(
                        ["Setpoint Type"]
                        + [Paragraph(u.get("setpoint_text", ""), body_style) for u in chunk]
                    )
                else:
                    rows.append(
                        ["TH21 Air (Thermistor)"]
                        + [Paragraph(u["th21_air"], body_style) for u in chunk]
                    )
                    rows.append(
                        ["TH24 Air (Thermistor)"]
                        + [Paragraph(u["th24_air"], body_style) for u in chunk]
                    )

                rows.append(
                    ["CNRM Jumper"]
                    + ["Connected" if u["cnrm_connected"] else "Disconnected"
                       for u in chunk]
                )
                rows.append(
                    ["Notes"]
                    + [", ".join(str(n) for n in per_unit_refs.get(u["tag"], []))
                       for u in chunk]
                )

                col_widths = [label_col] + [unit_col] * chunk_n
                table = Table(rows, colWidths=col_widths)
                ts = TableStyle([
                    ("BACKGROUND",   (0, 0), (0, -1), grey),
                    ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTSIZE",     (0, 0), (-1, -1), 9),
                    ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN",        (0, 0), (0, -1), "LEFT"),
                    ("LEFTPADDING",  (0, 0), (0, -1), 6),
                    ("FONTNAME",     (1, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID",         (0, 0), (-1, -1), 0.4, colors.black),
                    ("LEFTPADDING",  (1, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING",   (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ])
                table.setStyle(ts)
                story.append(table)
                story.append(Spacer(1, 12))
                story.extend(_guide_note_flowables())
                if chunk_idx < len(v_chunks) - 1:
                    story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()
