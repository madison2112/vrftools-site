"""Unit tests for web.lib.lev_kit_utils — LEV Kit switch logic and PDF rendering."""

from __future__ import annotations

import pytest

from web.lib.lev_kit_utils import (
    CONTROLLER_AH001,
    CONTROLLER_AH002,
    build_unit_record,
    compute_footnotes,
    generate_switch_positions,
    parse_dsbx,
    render_submittal_pdf,
)


class TestBuildUnitRecord:
    """Tests for build_unit_record — assembles a PDF-ready unit record."""

    @pytest.fixture
    def parsed_unit_ah002(self):
        """A minimal parsed unit matching the AH002 controller."""
        return {
            "tag": "Unit-A",
            "mnet": 50,
            "btuh": 8000,
            "capacity_index": 2,
            "capacity_label": "8 MBH",
            "lev_assembly": "PAC-LV24AC-1",
            "control_mode": "discharge",
            "raw_application_option": "Ventilation",
            "controller_type": CONTROLLER_AH002,
        }

    @pytest.fixture
    def parsed_unit_ah001(self):
        """A minimal parsed unit matching the AH001 controller."""
        return {
            "tag": "Unit-B",
            "mnet": 60,
            "btuh": 12000,
            "capacity_index": 3,
            "capacity_label": "12 MBH",
            "lev_assembly": "PAC-LV24AC-1",
            "control_mode": "discharge",
            "raw_application_option": "Ventilation",
            "controller_type": CONTROLLER_AH001,
        }

    def test_returns_dict(self, parsed_unit_ah002):
        record = build_unit_record(parsed_unit_ah002)
        assert isinstance(record, dict)

    def test_has_expected_keys(self, parsed_unit_ah002):
        record = build_unit_record(parsed_unit_ah002)
        assert record["tag"] == "Unit-A"
        assert "mnet" in record
        assert "switches" in record
        assert "cnrm_connected" in record
        assert "th21_air" in record
        assert "th24_air" in record
        assert "capacity_label" in record

    def test_switches_contain_expected_banks(self, parsed_unit_ah002):
        record = build_unit_record(parsed_unit_ah002)
        switches = record["switches"]
        for bank in ("SW1", "SW2", "SW3", "SW4", "SW21", "SW22"):
            assert bank in switches, f"Missing switch bank {bank}"
            assert isinstance(switches[bank], list)

    def test_ah001_controller(self, parsed_unit_ah001):
        record = build_unit_record(parsed_unit_ah001)
        assert record["controller_type"] == CONTROLLER_AH001
        # AH001 should have enable_text and setpoint_text
        assert "enable_text" in record
        assert "setpoint_text" in record

    def test_overrides_applied(self, parsed_unit_ah002):
        record = build_unit_record(
            parsed_unit_ah002,
            heat_pump=False,
            input_voltage="230",
        )
        assert record["heat_pump"] is False
        assert record["input_voltage"] == "230"

    def test_ah001_extra_fields_default(self, parsed_unit_ah001):
        record = build_unit_record(parsed_unit_ah001)
        assert record["fan_controlled_by"] == "bas"
        assert record["run_fan_defrost"] is False
        assert record["electric_heat"] is False

    def test_ah001_extra_fields_overridden(self, parsed_unit_ah001):
        record = build_unit_record(
            parsed_unit_ah001,
            fan_controlled_by="lev",
            electric_heat=True,
        )
        assert record["fan_controlled_by"] == "lev"
        assert record["electric_heat"] is True


class TestGenerateSwitchPositions:
    """Tests for generate_switch_positions with various configs."""

    @pytest.fixture
    def default_config(self):
        return {
            "controller_type": CONTROLLER_AH002,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }

    def test_returns_switches_and_cnrm(self, default_config):
        result = generate_switch_positions(default_config)
        assert "switches" in result
        assert "cnrm_connected" in result
        assert isinstance(result["switches"], dict)
        assert isinstance(result["cnrm_connected"], bool)

    def test_ah002_default_dat_mode_sw4_1_off(self, default_config):
        """SW4-1 should be OFF (0) in discharge mode."""
        result = generate_switch_positions(default_config)
        assert result["switches"]["SW4"][0] == 0

    def test_ah002_rat_mode_sw4_1_on(self, default_config):
        """SW4-1 should be ON (1) in return mode."""
        config = {**default_config, "control_mode": "return"}
        result = generate_switch_positions(config)
        assert result["switches"]["SW4"][0] == 1

    def test_ah002_cool_only_sw3_1_on(self, default_config):
        """SW3-1 should be ON for cooling-only units."""
        config = {**default_config, "heat_pump": False}
        result = generate_switch_positions(config)
        assert result["switches"]["SW3"][0] == 1

    def test_ah002_heat_pump_sw3_1_off(self, default_config):
        """SW3-1 should be OFF for heat pump units."""
        result = generate_switch_positions(default_config)
        assert result["switches"]["SW3"][0] == 0

    def test_capacity_sw2(self, default_config):
        """SW2 reflects the capacity bit pattern from the lookup table."""
        result = generate_switch_positions(default_config)
        # capacity=2 → 8 MBH → SW2 = [1, 0, 1, 0, 0, 0]
        assert result["switches"]["SW2"] == [1, 0, 1, 0, 0, 0]

    def test_voltage_208_sw21_6_on(self, default_config):
        """SW21-6 should be ON (1) for 208V."""
        result = generate_switch_positions(default_config)
        assert result["switches"]["SW21"][5] == 1

    def test_voltage_230_sw21_6_off(self, default_config):
        """SW21-6 should be OFF (0) for 230V."""
        config = {**default_config, "input_voltage": "230"}
        result = generate_switch_positions(config)
        assert result["switches"]["SW21"][5] == 0

    def test_ah001_controller_basic(self):
        """AH001 basic config should produce switches with SWA and SW5 banks."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 3,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
        result = generate_switch_positions(config)
        assert "SWA" in result["switches"]
        assert "SW5" in result["switches"]
        assert len(result["switches"]["SWA"]) == 3
        assert len(result["switches"]["SW5"]) == 1

    def test_unknown_capacity_raises(self, default_config):
        config = {**default_config, "capacity": 999}
        with pytest.raises(ValueError, match="Unknown capacity"):
            generate_switch_positions(config)

    def test_unknown_thermo_raises(self, default_config):
        config = {**default_config, "thermo_temp": 999}
        with pytest.raises(ValueError, match="Unknown thermo"):
            generate_switch_positions(config)


class TestGenerateSwitchPositionsAH001:
    """Tests specific to AH001 switch generation."""

    @pytest.fixture
    def ah001_dat_config(self):
        return {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }

    def test_ah001_sw5_voltage(self, ah001_dat_config):
        """SW5 represents voltage: 0=208V, 1=230V (single bit)."""
        result_208 = generate_switch_positions(
            {**ah001_dat_config, "input_voltage": "208"}
        )
        result_230 = generate_switch_positions(
            {**ah001_dat_config, "input_voltage": "230"}
        )
        assert result_208["switches"]["SW5"] == [0]
        assert result_230["switches"]["SW5"] == [1]


class TestRenderSubmittalPdf:
    """Smoke tests for render_submittal_pdf — validates PDF output signature."""

    @pytest.fixture
    def sample_unit(self):
        """Build a single unit record for PDF rendering."""
        parsed = {
            "tag": "TestUnit-1",
            "mnet": 1,
            "btuh": 8000,
            "capacity_index": 2,
            "capacity_label": "8 MBH",
            "lev_assembly": "PAC-LV24AC-1",
            "control_mode": "discharge",
            "raw_application_option": "Ventilation",
            "controller_type": CONTROLLER_AH002,
        }
        return build_unit_record(parsed)

    def test_returns_bytes(self, sample_unit):
        result = render_submittal_pdf(
            units=[sample_unit],
            project_name="Test Project",
            voltage="208",
            layout="horizontal",
        )
        assert isinstance(result, bytes)

    def test_starts_with_pdf_signature(self, sample_unit):
        result = render_submittal_pdf(
            units=[sample_unit],
            project_name="Test Project",
            voltage="208",
            layout="horizontal",
        )
        assert result[:4] == b"%PDF", f"Expected PDF signature, got {result[:10]!r}"

    def test_non_empty(self, sample_unit):
        result = render_submittal_pdf(
            units=[sample_unit],
            project_name="Test Project",
            voltage="208",
            layout="horizontal",
        )
        assert len(result) > 0

    def test_multiple_units(self):
        """PDF rendering with multiple units should still produce valid PDF."""
        parsed1 = {
            "tag": "Unit-1",
            "mnet": 1,
            "btuh": 8000,
            "capacity_index": 2,
            "capacity_label": "8 MBH",
            "lev_assembly": "PAC-LV24AC-1",
            "control_mode": "discharge",
            "raw_application_option": "Ventilation",
            "controller_type": CONTROLLER_AH002,
        }
        parsed2 = {
            "tag": "Unit-2",
            "mnet": 2,
            "btuh": 12000,
            "capacity_index": 3,
            "capacity_label": "12 MBH",
            "lev_assembly": "PAC-LV24AC-1",
            "control_mode": "return",
            "raw_application_option": "RoomAirConditioning",
            "controller_type": CONTROLLER_AH002,
        }
        unit1 = build_unit_record(parsed1)
        unit2 = build_unit_record(parsed2, control_mode="return")
        result = render_submittal_pdf(
            units=[unit1, unit2],
            project_name="Multi-Unit Test",
            voltage="230",
            layout="vertical",
        )
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF"
        assert len(result) > 0


class TestGenerateSwitchPositionsAH001More:
    """Tests for AH001-specific switch branches not covered by the AH002 tests."""

    def test_ah001_rat_mode_sw1_1_on(self):
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW1"][0] == 1

    def test_ah001_dat_mode_sw1_1_off(self):
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW1"][0] == 0

    def test_ah001_cool_only_sw2_1_on(self):
        """Cool-only units set SW2[1]=1 in AH001 (unlike AH002 which uses SW3-1)."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": False,
            "input_voltage": "208",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW2"][1] == 1

    def test_ah001_rat_mode_sw3_2_on(self):
        """RAT mode always sets SW3[2]=1 (enable method flag)."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW3"][2] == 1

    def test_ah001_dat_bas_enable_sw3_2_on(self):
        """DAT mode with BAS enable also sets SW3[2]=1."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 3,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "discharge_enable": "bas",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW3"][2] == 1

    def test_ah001_dat_bas_enable_and_setpoint_swa_1(self):
        """When both enable and setpoint are BAS in DAT mode, SWA[1]=1."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 3,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "discharge_enable": "bas",
            "discharge_setpoint": "bas",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SWA"][1] == 1

    def test_ah001_electric_heat_sw2_2_and_sw3_1(self):
        """Electric heat sets SW2[2]=1 and SW3[1]=1 in AH001."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "electric_heat": True,
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW2"][2] == 1
        assert result["switches"]["SW3"][1] == 1

    def test_ah001_rat_mode_swa_0(self):
        """RAT mode sets SWA[0]=1."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SWA"][0] == 1

    def test_ah001_dat_bas_enable_cnrm_connected(self):
        """DAT mode with BAS enable should connect CNRM."""
        config = {
            "controller_type": CONTROLLER_AH001,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "discharge_enable": "bas",
        }
        result = generate_switch_positions(config)
        assert result["cnrm_connected"] is True


class TestGenerateSwitchPositionsAH002More:
    """Tests for more AH002 switch branches."""

    def test_dat_bas_enable_and_setpoint(self):
        """SW21-1/2 should both be 0 when both enable and setpoint are BAS in DAT mode."""
        config = {
            "controller_type": CONTROLLER_AH002,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "discharge_enable": "bas",
            "discharge_setpoint": "bas",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW21"][0] == 0
        assert result["switches"]["SW21"][1] == 0

    def test_rat_mode_temp_adjustment(self):
        """SW3-8 OFF and SW3-4 ON when RAT mode with temp_adjustment."""
        config = {
            "controller_type": CONTROLLER_AH002,
            "capacity": 2,
            "control_mode": "return",
            "heat_pump": True,
            "input_voltage": "208",
            "temp_adjustment": True,
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW3"][7] == 0  # SW3-8 OFF
        assert result["switches"]["SW3"][3] == 1  # SW3-4 ON

    def test_dat_thermo_temp_encoding(self):
        """DAT mode with thermo_temp=3 should set SW3-8 and SW3-9 from lookup."""
        config = {
            "controller_type": CONTROLLER_AH002,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "thermo_temp": 3,  # Thermo OFF at 70°F → sw3=[0,0]
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW3"][7] == 0  # SW3-8
        assert result["switches"]["SW3"][8] == 0  # SW3-9

    def test_dat_setpoint_82(self):
        """SW3-10 should be OFF when dat_setpoint=1 (82°F limit)."""
        config = {
            "controller_type": CONTROLLER_AH002,
            "capacity": 2,
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
            "dat_setpoint": 1,
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW3"][9] == 0

    def test_capacity_16_dual_lev(self):
        """SW3-6 should be ON when capacity >= 16 (dual LEV)."""
        config = {
            "controller_type": CONTROLLER_AH002,
            "capacity": 16,  # 144 MBH
            "control_mode": "discharge",
            "heat_pump": True,
            "input_voltage": "208",
        }
        result = generate_switch_positions(config)
        assert result["switches"]["SW3"][5] == 1


class TestComputeFootnotes:
    """Tests for compute_footnotes."""

    @pytest.fixture
    def sample_units(self):
        parsed1 = {
            "tag": "Unit-1",
            "mnet": 1,
            "btuh": 8000,
            "capacity_index": 2,
            "capacity_label": "8 MBH",
            "lev_assembly": "PAC-LV24AC-1",
            "control_mode": "discharge",
            "raw_application_option": "Ventilation",
            "controller_type": CONTROLLER_AH002,
        }
        unit1 = build_unit_record(parsed1)
        unit2 = build_unit_record(
            {
                "tag": "Unit-2",
                "mnet": 2,
                "btuh": 8000,
                "capacity_index": 2,
                "capacity_label": "8 MBH",
                "lev_assembly": "PAC-LV24AC-1",
                "control_mode": "discharge",
                "raw_application_option": "Ventilation",
                "controller_type": CONTROLLER_AH002,
            },
            heat_pump=False,
        )
        return [unit1, unit2]

    def test_returns_tuple_of_lists(self, sample_units):
        lines, refs = compute_footnotes(sample_units)
        assert isinstance(lines, list)
        assert isinstance(refs, dict)

    def test_footnotes_detected_for_non_default(self, sample_units):
        lines, refs = compute_footnotes(sample_units)
        # Unit-2 has heat_pump=False (cool-only) which should produce a note
        assert len(lines) > 0
        assert "Unit-2" in refs


class TestParseDsbx:
    """Tests for parse_dsbx — LEV Kit DSBX parser."""

    def test_empty_bytes_raises(self):
        with pytest.raises(ValueError, match="Not a valid"):
            parse_dsbx(b"")

    def test_malformed_bytes_raises(self):
        with pytest.raises(ValueError, match="Not a valid"):
            parse_dsbx(b"not a real dsbx file")

    def test_minimal_dsbx_with_lev_kit(self):
        """A minimal DSBX with one LEV Kit indoor unit."""
        import io
        import zipfile
        import xml.etree.ElementTree as ET_mod

        root = ET_mod.Element("Root")
        ET_mod.SubElement(root, "ProjectName").text = "TestProject"
        idu = ET_mod.SubElement(root, "IndoorUnit")
        # Model must contain "LEV KIT" (case-insensitive) AND a capacity like "n Btu/h"
        ET_mod.SubElement(idu, "ModelNumber").text = "PAC-AH002 LEV KIT (R32) 8000 Btu/h"
        ET_mod.SubElement(idu, "ReferenceTag").text = "Unit-A"
        ET_mod.SubElement(idu, "LEVApplicationOption").text = "Ventilation"
        ET_mod.SubElement(idu, "MNetAddress").text = "50"
        xml_bytes = ET_mod.tostring(root, encoding="utf-8")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xml", xml_bytes.decode("utf-8-sig"))
        dsbx_data = buf.getvalue()

        result = parse_dsbx(dsbx_data)
        assert "project_name" in result
        assert "units" in result
        assert "controllers_found" in result
        assert "warnings" in result
        assert result["project_name"] == "TestProject"
        assert len(result["units"]) >= 1

    def test_dsbx_without_xml_member_raises(self):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("not_xml", "nope")
        with pytest.raises(ValueError, match="missing 'xml'"):
            parse_dsbx(buf.getvalue())
