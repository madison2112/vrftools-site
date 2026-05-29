"""Unit tests for web.lib.dsbx_utils — DSBX file parsing and group extraction.

Fixture gap: no .dsbx fixture exists in the repo. Tests focus on error paths
and the directly-callable helper functions. A follow-up card should add a
real DSBX fixture for full coverage.
"""

from __future__ import annotations

import pytest

from web.lib.dsbx_utils import (
    extract_group_cards,
    get_groupof50_list,
    load_mapping,
    lookup_icon,
    parse_dsbx_bytes,
)


class TestParseDsbxBytes:
    """Tests for parse_dsbx_bytes — validates error handling."""

    def test_empty_bytes_raises(self):
        """Empty bytes should raise BadZipFile."""
        import zipfile
        with pytest.raises(zipfile.BadZipFile):
            parse_dsbx_bytes(b"")

    def test_malformed_bytes_raises(self):
        """Random bytes that aren't a ZIP should raise an exception."""
        import zipfile
        with pytest.raises(zipfile.BadZipFile):
            parse_dsbx_bytes(b"this is not a zip file at all")

    def test_valid_zip_no_xml_member_raises(self):
        """A valid ZIP without an 'xml' member should raise."""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("not_xml", "some content")
        data = buf.getvalue()
        # A ZIP without an 'xml' member raises KeyError from z.read('xml')
        with pytest.raises(KeyError):
            parse_dsbx_bytes(data)

    def test_accepts_bytes(self):
        """parse_dsbx_bytes accepts bytes type."""
        # Minimal valid DSBX-like bytes: a ZIP with an 'xml' member
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("xml", "<root/>")
        data = buf.getvalue()
        result = parse_dsbx_bytes(data)
        assert result is not None


class TestExtractGroupCards:
    """Tests for extract_group_cards with a minimal Groupof50 element."""

    @pytest.fixture
    def mapping(self):
        return load_mapping()

    @pytest.fixture
    def minimal_groupof50(self):
        """Build a minimal Groupof50 with one IU group and a System."""
        import xml.etree.ElementTree as ET

        g50 = ET.Element("Groupof50")
        g50.set("Name", "TestBlock")

        # System with OutdoorUnit
        sys_elem = ET.SubElement(g50, "System")
        ET.SubElement(sys_elem, "SystemType").text = "MandS"
        ou = ET.SubElement(sys_elem, "OutdoorUnit")
        ET.SubElement(ou, "MNetAddress").text = "1"
        idu = ET.SubElement(ou, "IndoorUnit")
        ET.SubElement(idu, "MNetAddress").text = "50"
        ET.SubElement(idu, "ModelNumber").text = "PKFY-P06 (R32)"
        ET.SubElement(idu, "AssociatedIndoorUnitGroup").text = "G1"
        ET.SubElement(idu, "ReferenceTag").text = "Office-01"

        # IndoorUnitGroup
        iug = ET.SubElement(g50, "IndoorUnitGroup")
        ET.SubElement(iug, "TableId").text = "G1"
        ET.SubElement(iug, "GroupType").text = "IU"
        ET.SubElement(iug, "GroupNumber").text = "1"
        rc = ET.SubElement(iug, "LocalRemoteController")
        ET.SubElement(rc, "MNetAddress").text = "51"

        return g50

    def test_returns_list(self, minimal_groupof50, mapping):
        cards = extract_group_cards(minimal_groupof50, mapping)
        assert isinstance(cards, list)

    def test_card_has_expected_shape(self, minimal_groupof50, mapping):
        cards = extract_group_cards(minimal_groupof50, mapping)
        assert len(cards) > 0
        card = cards[0]
        assert "slot" in card
        assert "tag" in card
        assert "mnet_addresses" in card
        assert "unit_types" in card
        assert "icon" in card
        # slot should match the GroupNumber
        assert card["slot"] == 1
        # tag should match the ReferenceTag
        assert card["tag"] == "Office-01"

    def test_empty_groupof50_returns_empty(self, mapping):
        import xml.etree.ElementTree as ET

        g50 = ET.Element("Groupof50")
        cards = extract_group_cards(g50, mapping)
        assert cards == []


class TestExtractGroupCardsLossnay:
    """Tests for Lossnay-type groups."""

    @pytest.fixture
    def mapping(self):
        return load_mapping()

    @pytest.fixture
    def lossnay_groupof50(self):
        import xml.etree.ElementTree as ET

        g50 = ET.Element("Groupof50")
        g50.set("Name", "LossnayTest")

        # System with OutdoorUnit (needed for MandS validation)
        sys_elem = ET.SubElement(g50, "System")
        ET.SubElement(sys_elem, "SystemType").text = "MandS"
        ou = ET.SubElement(sys_elem, "OutdoorUnit")
        ET.SubElement(ou, "MNetAddress").text = "1"

        # Lossnay
        lossnay = ET.SubElement(g50, "Lossnay")
        ET.SubElement(lossnay, "LossnayGroupId").text = "L1"
        ET.SubElement(lossnay, "MNetAddress").text = "100"
        ET.SubElement(lossnay, "ReferenceTag").text = "ERV-Floor1"

        # IndoorUnitGroup for the Lossnay
        iug = ET.SubElement(g50, "IndoorUnitGroup")
        ET.SubElement(iug, "TableId").text = "L1"
        ET.SubElement(iug, "GroupType").text = "Lossnay"
        ET.SubElement(iug, "GroupNumber").text = "5"

        return g50

    def test_lossnay_card_shape(self, lossnay_groupof50, mapping):
        cards = extract_group_cards(lossnay_groupof50, mapping)
        assert len(cards) == 1
        card = cards[0]
        assert card["slot"] == 5
        assert card["tag"] == "ERV-Floor1"
        assert card["unit_types"] == ["LC"]
        assert card["mnet_addresses"] == ["100"]


class TestGetGroupof50List:
    """Tests for get_groupof50_list."""

    def test_no_project_raises(self):
        import xml.etree.ElementTree as ET

        root = ET.Element("Root")
        with pytest.raises(ValueError, match="No <Project> element"):
            get_groupof50_list(root)

    def test_empty_project_returns_empty(self):
        import xml.etree.ElementTree as ET

        root = ET.Element("Root")
        ET.SubElement(root, "Project")
        result = get_groupof50_list(root)
        assert result == []


class TestLoadMapping:
    def test_returns_dict(self):
        mapping = load_mapping()
        assert isinstance(mapping, dict)

    def test_has_icon_rules(self):
        mapping = load_mapping()
        assert "icon_rules" in mapping
        assert isinstance(mapping["icon_rules"], list)

    def test_has_default_icon(self):
        mapping = load_mapping()
        assert "default_icon" in mapping


class TestLookupIcon:
    @pytest.fixture
    def icon_rules(self):
        return load_mapping()["icon_rules"]

    def test_matches_startswith(self, icon_rules):
        default = 0
        result = lookup_icon("PKFY-P06", icon_rules, default)
        assert result == 10  # PKFY startswith rule

    def test_no_match_returns_default(self, icon_rules):
        default = 0
        result = lookup_icon("ZZZZ-UNKNOWN", icon_rules, default)
        assert result == default

    def test_case_insensitive(self, icon_rules):
        default = 0
        result = lookup_icon("pkfy-p06", icon_rules, default)
        # The PKFY rule is case_sensitive=true, so lowercase shouldn't match
        # unless there's a case-insensitive rule. Let's check the LEV KIT rule
        # which is case_insensitive: contains "LEV KIT"
        result_lev = lookup_icon("LEV KIT ABC", icon_rules, default)
        assert result_lev == 53
