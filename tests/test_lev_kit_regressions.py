"""Regression tests for LEV Kit switch logic fixes.

Run:  python3 tests/test_lev_kit_regressions.py
"""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web", "lib"))

from lev_kit_utils import generate_switch_positions, CONTROLLER_AH001, CONTROLLER_AH002

PASS = 0
FAIL = 0


def check(label, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}")
        print(f"        expected={expected}")
        print(f"        actual  ={actual}")


def test_ah002_sw4_1_toggles_with_mode():
    """Bug 1: SW4-1 ON in RAT, OFF in DAT"""
    print("\n── AH002 Bug 1: SW4-1 toggles with mode ──")
    dat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH002,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    rat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH002,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    check("SW4-1 OFF in DAT", dat["switches"]["SW4"][0], 0)
    check("SW4-1 ON  in RAT", rat["switches"]["SW4"][0], 1)


def test_ah001_sw1_1_for_rat():
    """Bug 5: SW1-1 ON for RAT mode"""
    print("\n── AH001 Bug 5: SW1-1 ON for RAT ──")
    dat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    rat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    check("SW1-1 OFF in DAT", dat["switches"]["SW1"][0], 0)
    check("SW1-1 ON  in RAT", rat["switches"]["SW1"][0], 1)


def test_ah001_sw4_1_toggles():
    """Bug 6: SW4-1 OFF in DAT, ON in RAT"""
    print("\n── AH001 Bug 6: SW4-1 OFF in DAT, ON in RAT ──")
    dat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    rat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    check("SW4-1 OFF in DAT", dat["switches"]["SW4"][0], 0)
    check("SW4-1 ON  in RAT", rat["switches"]["SW4"][0], 1)


def test_ah001_sw3_2_electric_heat():
    """Bug 8a: SW3-2 ON when electric heat installed"""
    print("\n── AH001 Bug 8a: SW3-2 ON when electric heat ──")
    # RAT with electric heat -> SW3-2 should be ON
    rat_eh = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "electric_heat": True,
            "fan_controlled_by": "lev",
        }
    )
    # RAT without electric heat -> SW3-2 should be ON (RAT mode flag)
    rat_noeh = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "electric_heat": False,
        }
    )
    # DAT without electric heat -> SW3-2 should be OFF
    dat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    check("SW3-2 ON  with electric heat (RAT)", rat_eh["switches"]["SW3"][1], 1)
    check("SW3-2 ON  without electric heat (RAT)", rat_noeh["switches"]["SW3"][1], 1)
    check("SW3-2 OFF in DAT without EH", dat["switches"]["SW3"][1], 0)


def test_ah001_sw3_4_defrost_gating():
    """Bug 8b: SW3-4 correct defrost logic"""
    print("\n── AH001 Bug 8b: SW3-4 defrost gating ──")

    # DAT + LEV fan + run fan defrost → ON
    dat_fan_on = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "fan_controlled_by": "lev",
            "run_fan_defrost": True,
        }
    )
    # DAT + BAS fan → OFF (even if run_fan_defrost were set, but it's gated)
    dat_bas_fan = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "fan_controlled_by": "bas",
            "run_fan_defrost": False,
        }
    )
    # RAT + electric heat + use defrost → ON
    rat_eh_def = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "electric_heat": True,
            "use_defrost_error": True,
            "fan_controlled_by": "lev",
        }
    )
    # RAT + electric heat NO defrost → OFF
    rat_eh_nodef = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "electric_heat": True,
            "use_defrost_error": False,
            "fan_controlled_by": "lev",
        }
    )

    check("SW3-4 ON  DAT+LEV fan+defrost", dat_fan_on["switches"]["SW3"][3], 1)
    check("SW3-4 OFF DAT+BAS fan", dat_bas_fan["switches"]["SW3"][3], 0)
    check("SW3-4 ON  RAT+EH+defrost", rat_eh_def["switches"]["SW3"][3], 1)
    check("SW3-4 OFF RAT+EH no defrost", rat_eh_nodef["switches"]["SW3"][3], 0)


def test_ah001_sw3_8_stratification():
    """Bug 8c: SW3-8 ON when stratification OFF in RAT"""
    print("\n── AH001 Bug 8c: SW3-8 inverted in RAT ──")
    rat_adj_off = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "temp_adjustment": False,
        }
    )
    rat_adj_on = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "temp_adjustment": True,
        }
    )
    check("SW3-8 ON  when stratification OFF", rat_adj_off["switches"]["SW3"][7], 1)
    check("SW3-8 OFF when stratification ON", rat_adj_on["switches"]["SW3"][7], 0)


def test_ah001_thermo_unit_vent():
    """AH001 thermo-off value 2 (N/A for Unit Vent) sets SW3-8 ON, SW3-9 OFF"""
    print("\n── AH001 Thermo Unit Vent: SW3[7]=1, SW3[8]=0 ──")
    dat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "thermo_temp": 2,
        }
    )
    # thermo value 2 = N/A for Unit Vent → sw3=[1,0]
    # which maps to SW3[7]=1, SW3[8]=0
    check("SW3-8 ON  (unit vent)", dat["switches"]["SW3"][7], 1)
    check("SW3-9 OFF (unit vent)", dat["switches"]["SW3"][8], 0)


def test_ah001_sw4_7_8_control_mode():
    """AH001 SW4-7 and SW4-8 are control-mode settings, not thermo-off"""
    print("\n── AH001 SW4-7/SW4-8: ON/ON in DAT, OFF/OFF in RAT ──")
    dat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    rat = generate_switch_positions(
        {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
        }
    )
    check("SW4-7 ON  in DAT", dat["switches"]["SW4"][6], 1)
    check("SW4-8 ON  in DAT", dat["switches"]["SW4"][7], 1)
    check("SW4-7 OFF in RAT", rat["switches"]["SW4"][6], 0)
    check("SW4-8 OFF in RAT", rat["switches"]["SW4"][7], 0)


if __name__ == "__main__":
    test_ah002_sw4_1_toggles_with_mode()
    test_ah001_sw1_1_for_rat()
    test_ah001_sw4_1_toggles()
    test_ah001_sw3_2_electric_heat()
    test_ah001_sw3_4_defrost_gating()
    test_ah001_sw3_8_stratification()
    test_ah001_thermo_unit_vent()
    test_ah001_sw4_7_8_control_mode()
    print(f"\n{'=' * 50}")
    print(f"Results: {PASS} passed, {FAIL} failed out of {PASS + FAIL}")
    if FAIL:
        sys.exit(1)
