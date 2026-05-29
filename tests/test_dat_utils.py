"""Unit tests for web.lib.dat_utils — core DAT file parsing and manipulation."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from web.lib.dat_utils import (
    apply_group_names,
    apply_rearrangement,
    convert_dat_bytes,
    detect_controller_type,
    extract_groups_from_xml,
    generate_dat_bytes,
    parse_dat_controllers,
    rearrange_and_convert_dat_bytes,
    rearrange_and_repackage_dat_bytes,
    rearrange_and_split_dat_bytes,
    rearrange_dat_bytes,
    safe_filename,
    sort_groups_by_tag,
    split_dat_bytes,
)


class TestParseDatControllers:
    """Tests for parse_dat_controllers using the sample empty AE-C400 fixture."""

    def test_returns_list(self, sample_dat_bytes):
        result = parse_dat_controllers(sample_dat_bytes)
        assert isinstance(result, list)

    def test_each_entry_has_required_keys(self, sample_dat_bytes):
        controllers = parse_dat_controllers(sample_dat_bytes)
        for ctrl in controllers:
            assert "entry" in ctrl
            assert "name" in ctrl
            assert "controller_type" in ctrl
            assert "xml_bytes" in ctrl

    def test_controller_type_is_known(self, sample_dat_bytes):
        controllers = parse_dat_controllers(sample_dat_bytes)
        valid_types = {"AE-200", "AE-C400A", "EW-50", "EW-C50"}
        for ctrl in controllers:
            assert ctrl["controller_type"] in valid_types

    def test_empty_bytes_raises(self):
        """Empty bytes should raise because it's not a valid ZIP."""
        import pyzipper
        with pytest.raises(pyzipper.BadZipFile):
            parse_dat_controllers(b"")


class TestExtractGroupsFromXml:
    """Tests for extract_groups_from_xml — parses ControlGroup XML to card dicts."""

    @pytest.fixture
    def sample_xml_bytes(self, sample_dat_bytes):
        """Extract xml_bytes from the first controller in the fixture."""
        controllers = parse_dat_controllers(sample_dat_bytes)
        assert len(controllers) > 0, "Fixture should have at least one controller"
        return controllers[0]["xml_bytes"]

    def test_returns_list(self, sample_xml_bytes):
        result = extract_groups_from_xml(sample_xml_bytes)
        assert isinstance(result, list)

    def test_each_card_has_expected_keys(self, sample_xml_bytes):
        cards = extract_groups_from_xml(sample_xml_bytes)
        for card in cards:
            assert "slot" in card
            assert "tag" in card
            assert "mnet_addresses" in card
            assert "unit_types" in card
            assert "icon" in card
            assert isinstance(card["slot"], int)
            assert isinstance(card["tag"], str)

    def test_no_controlgroup_returns_empty(self):
        """XML without a ControlGroup element should return empty list."""
        root = ET.Element("Root")
        xml_bytes = ET.tostring(root, encoding="utf-8")
        result = extract_groups_from_xml(xml_bytes)
        assert result == []


class TestApplyRearrangement:
    """Tests for apply_rearrangement — remaps Group numbers per new_order."""

    @pytest.fixture
    def sample_xml_bytes(self, sample_dat_bytes):
        controllers = parse_dat_controllers(sample_dat_bytes)
        assert len(controllers) > 0
        return controllers[0]["xml_bytes"]

    def test_no_controlgroup_returns_original(self):
        """XML without ControlGroup should pass through unchanged."""
        xml_bytes = b"<Root><Other/></Root>"
        result = apply_rearrangement(xml_bytes, [1, 2, 3])
        assert result == xml_bytes

    def test_non_empty_result(self, sample_xml_bytes):
        """Rearrangement should produce valid XML bytes."""
        result = apply_rearrangement(sample_xml_bytes, [1])
        assert isinstance(result, bytes)
        assert len(result) > 0
        # Should be valid XML
        ET.fromstring(result)

    def test_empty_new_order(self, sample_xml_bytes):
        """Empty new_order should still produce valid XML."""
        result = apply_rearrangement(sample_xml_bytes, [])
        assert isinstance(result, bytes)
        assert len(result) > 0
        ET.fromstring(result)


class TestApplyGroupNames:
    """Tests for apply_group_names — writes GroupNameWeb attributes on MnetRecords."""

    @pytest.fixture
    def sample_xml_bytes(self, sample_dat_bytes):
        controllers = parse_dat_controllers(sample_dat_bytes)
        assert len(controllers) > 0
        return controllers[0]["xml_bytes"]

    def test_empty_tag_map_returns_original(self, sample_xml_bytes):
        result = apply_group_names(sample_xml_bytes, {})
        assert result == sample_xml_bytes

    def test_produces_valid_xml(self, sample_xml_bytes):
        result = apply_group_names(sample_xml_bytes, {1: "Test-Group"})
        assert isinstance(result, bytes)
        assert len(result) > 0
        ET.fromstring(result)

    def test_no_controlgroup_returns_original(self):
        xml_bytes = b"<Root><Other/></Root>"
        result = apply_group_names(xml_bytes, {1: "Test"})
        assert result == xml_bytes


class TestSortGroupsByTag:
    """Tests for sort_groups_by_tag — natural-sort IC/AIC slots by tag name."""

    def test_empty_list(self):
        result = sort_groups_by_tag([])
        assert result == []

    def test_returns_list_of_ints(self):
        cards = [
            {"slot": 2, "tag": "IDU-2", "unit_types": ["IC"], "mnet_addresses": ["2"], "icon": 0},
            {"slot": 1, "tag": "IDU-1", "unit_types": ["IC"], "mnet_addresses": ["1"], "icon": 0},
            {"slot": 10, "tag": "IDU-10", "unit_types": ["IC"], "mnet_addresses": ["10"], "icon": 0},
        ]
        result = sort_groups_by_tag(cards)
        assert isinstance(result, list)
        assert all(isinstance(s, int) for s in result)

    def test_natural_sort_order(self):
        cards = [
            {"slot": 2, "tag": "IDU-2", "unit_types": ["IC"], "mnet_addresses": ["2"], "icon": 0},
            {"slot": 10, "tag": "IDU-10", "unit_types": ["IC"], "mnet_addresses": ["10"], "icon": 0},
            {"slot": 1, "tag": "IDU-1", "unit_types": ["IC"], "mnet_addresses": ["1"], "icon": 0},
        ]
        result = sort_groups_by_tag(cards)
        # Natural sort: IDU-1, IDU-2, IDU-10 (not IDU-1, IDU-10, IDU-2)
        assert result == [1, 2, 10]

    def test_lc_groups_follow_ic(self):
        cards = [
            {"slot": 3, "tag": "LC-A", "unit_types": ["LC"], "mnet_addresses": ["3"], "icon": 0},
            {"slot": 1, "tag": "IDU-1", "unit_types": ["IC"], "mnet_addresses": ["1"], "icon": 0},
            {"slot": 2, "tag": "LC-B", "unit_types": ["LC"], "mnet_addresses": ["2"], "icon": 0},
        ]
        result = sort_groups_by_tag(cards)
        # IC slots first, LC slots last
        assert result[0] == 1  # IDU-1 first
        assert result[-2:] == [3, 2] or result[-2:] == [2, 3]  # LC slots at end

    def test_other_slots_between_ic_and_lc(self):
        cards = [
            {"slot": 3, "tag": "LC-A", "unit_types": ["LC"], "mnet_addresses": ["3"], "icon": 0},
            {"slot": 1, "tag": "IDU-1", "unit_types": ["IC"], "mnet_addresses": ["1"], "icon": 0},
            {"slot": 5, "tag": "Other", "unit_types": ["XX"], "mnet_addresses": ["5"], "icon": 0},
        ]
        result = sort_groups_by_tag(cards)
        assert result[0] == 1      # IC first
        assert result[-1] == 3     # LC last
        assert result[1] == 5      # other in middle


class TestSafeFilename:
    """Tests for safe_filename — sanitizes filenames for OS compatibility."""

    def test_preserves_simple_name(self):
        assert safe_filename("Floor-01") == "Floor-01"

    def test_replaces_special_chars(self):
        name = "Floor:01<test>"
        result = safe_filename(name)
        for ch in r'\/:*?"<>|':
            assert ch not in result

    def test_empty_or_whitespace_returns_unnamed(self):
        assert safe_filename("   ") == "unnamed"
        assert safe_filename("") == "unnamed"


class TestDetectControllerType:
    """Tests for detect_controller_type using the sample fixture."""

    def test_returns_known_type(self, sample_dat_bytes):
        ctype = detect_controller_type(sample_dat_bytes)
        assert ctype in {"AE-200", "AE-C400A", "EW-50", "EW-C50"}

    def test_returns_string(self, sample_dat_bytes):
        ctype = detect_controller_type(sample_dat_bytes)
        assert isinstance(ctype, str)
        assert len(ctype) > 0


class TestGenerateDatBytes:
    """Tests for generate_dat_bytes — wraps XML in encrypted DAT ZIP."""

    @pytest.fixture
    def sample_xml(self, sample_dat_bytes):
        controllers = parse_dat_controllers(sample_dat_bytes)
        assert len(controllers) > 0
        return controllers[0]["xml_bytes"]

    @pytest.fixture
    def sample_controller_type(self, sample_dat_bytes):
        controllers = parse_dat_controllers(sample_dat_bytes)
        assert len(controllers) > 0
        return controllers[0]["controller_type"]

    def test_returns_bytes(self, sample_xml, sample_controller_type):
        result = generate_dat_bytes(sample_xml, sample_controller_type)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_produces_valid_zip(self, sample_xml, sample_controller_type):
        result = generate_dat_bytes(sample_xml, sample_controller_type)
        # Should be parseable back
        re_parsed = parse_dat_controllers(result)
        assert len(re_parsed) > 0

    def test_ae200_no_network_no_img(self):
        """AE-200 should work without network or IMG entries."""
        # Build minimal valid XML
        root = ET.Element("Root")
        cg = ET.SubElement(root, "ControlGroup")
        ET.SubElement(cg, "MnetGroupList")
        ET.SubElement(cg, "ViewInfoList")
        ET.SubElement(cg, "MnetList")
        xml = ET.tostring(root, encoding="utf-8")
        result = generate_dat_bytes(xml, "AE-200")
        assert isinstance(result, bytes)
        assert len(result) > 0


class TestConvertDatBytes:
    """Tests for convert_dat_bytes — converts controllers to opposite family."""

    def test_returns_list(self, sample_dat_bytes):
        result = convert_dat_bytes(sample_dat_bytes)
        assert isinstance(result, list)

    def test_each_result_has_expected_keys(self, sample_dat_bytes):
        results = convert_dat_bytes(sample_dat_bytes)
        for item in results:
            assert "name" in item
            assert "controller" in item
            assert "data" in item
            assert isinstance(item["data"], bytes)
            assert len(item["data"]) > 0

    def test_result_is_valid_dat(self, sample_dat_bytes):
        """Converted result should be parseable."""
        results = convert_dat_bytes(sample_dat_bytes)
        for item in results:
            re_parsed = parse_dat_controllers(item["data"])
            assert len(re_parsed) > 0


class TestSplitDatBytes:
    """Tests for split_dat_bytes — splits multi-controller DATs."""

    def test_single_controller_raises(self, sample_dat_bytes):
        """The sample fixture has one controller — splitting should raise."""
        with pytest.raises(ValueError, match="only one controller"):
            split_dat_bytes(sample_dat_bytes)


class TestRearrangeDatBytes:
    """Tests for rearrange_dat_bytes — applies rearrangement to a single-controller DAT."""

    @pytest.fixture
    def sample_order(self, sample_dat_bytes):
        controllers = parse_dat_controllers(sample_dat_bytes)
        assert len(controllers) > 0
        xml = controllers[0]["xml_bytes"]
        cards = extract_groups_from_xml(xml)
        # Use the slot numbers found as the order (identity rearrangement)
        return [c["slot"] for c in cards]

    def test_returns_bytes(self, sample_dat_bytes, sample_order):
        result = rearrange_dat_bytes(sample_dat_bytes, sample_order)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_result_is_parseable(self, sample_dat_bytes, sample_order):
        result = rearrange_dat_bytes(sample_dat_bytes, sample_order)
        re_parsed = parse_dat_controllers(result)
        assert len(re_parsed) > 0

    def test_could_not_parse_raises(self, sample_order):
        """Invalid DAT bytes should raise."""
        import pyzipper
        with pytest.raises(pyzipper.BadZipFile):
            rearrange_dat_bytes(b"not-a-valid-dat-file", sample_order)

    def test_multi_controller_raises(self):
        """Build a multi-controller DAT to test the multi-controller guard."""
        # Create two XML controllers
        root1 = ET.Element("Root")
        ET.SubElement(root1, "SystemData", Name="Ctrl1", Model="AE-200")
        ET.SubElement(root1, "ControlGroup")
        xml1 = ET.tostring(root1, encoding="utf-8")

        root2 = ET.Element("Root")
        ET.SubElement(root2, "SystemData", Name="Ctrl2", Model="AE-200")
        ET.SubElement(root2, "ControlGroup")
        xml2 = ET.tostring(root2, encoding="utf-8")

        # Build a multi-controller DAT using multiple entries
        import io
        import pyzipper
        from web.lib.zipcrypto import PASSWORD

        buf = io.BytesIO()
        with pyzipper.AESZipFile(buf, "w", compression=pyzipper.ZIP_DEFLATED,
                                 encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(PASSWORD)
            zf.writestr("1", xml1)
            zf.writestr("2", xml2)
        multi_dat = buf.getvalue()

        with pytest.raises(ValueError, match="single-controller"):
            rearrange_dat_bytes(multi_dat, [1])


class TestRearrangeAndRepackageDatBytes:
    """Tests for rearrange_and_repackage_dat_bytes."""

    def test_identity_rearrangement(self, sample_dat_bytes):
        """An empty orders dict should produce valid output."""
        result = rearrange_and_repackage_dat_bytes(sample_dat_bytes, {})
        assert isinstance(result, bytes)
        assert len(result) > 0
        # Should be parseable
        re_parsed = parse_dat_controllers(result)
        assert len(re_parsed) > 0


class TestRearrangeAndSplitDatBytes:
    """Tests for rearrange_and_split_dat_bytes."""

    def test_identity_rearrangement(self, sample_dat_bytes):
        """Empty orders dict, single controller — produces one split result."""
        result = rearrange_and_split_dat_bytes(sample_dat_bytes, {})
        assert isinstance(result, list)
        assert len(result) == 1
        item = result[0]
        assert "name" in item
        assert "controller" in item
        assert "data" in item
        assert isinstance(item["data"], bytes)
        assert len(item["data"]) > 0


class TestSplitDatBytesMulti:
    """Tests for split_dat_bytes with a multi-controller DAT."""

    @pytest.fixture
    def multi_dat(self):
        """Build a two-controller DAT (both AE-200, no network/img)."""
        import io
        import pyzipper
        from web.lib.zipcrypto import PASSWORD

        root1 = ET.Element("Root")
        ET.SubElement(root1, "SystemData", Name="Ctrl-A", Model="AE-200")
        cg1 = ET.SubElement(root1, "ControlGroup")
        ET.SubElement(cg1, "MnetGroupList")
        ET.SubElement(cg1, "ViewInfoList")
        ET.SubElement(cg1, "MnetList")
        xml1 = ET.tostring(root1, encoding="utf-8")

        root2 = ET.Element("Root")
        ET.SubElement(root2, "SystemData", Name="Ctrl-B", Model="AE-200")
        cg2 = ET.SubElement(root2, "ControlGroup")
        ET.SubElement(cg2, "MnetGroupList")
        ET.SubElement(cg2, "ViewInfoList")
        ET.SubElement(cg2, "MnetList")
        xml2 = ET.tostring(root2, encoding="utf-8")

        buf = io.BytesIO()
        with pyzipper.AESZipFile(buf, "w", compression=pyzipper.ZIP_DEFLATED,
                                 encryption=pyzipper.WZ_AES) as zf:
            zf.setpassword(PASSWORD)
            zf.writestr("1", xml1)
            zf.writestr("2", xml2)
        return buf.getvalue()

    def test_splits_into_two(self, multi_dat):
        result = split_dat_bytes(multi_dat)
        assert len(result) == 2

    def test_each_result_has_expected_shape(self, multi_dat):
        results = split_dat_bytes(multi_dat)
        for item in results:
            assert "name" in item
            assert "controller" in item
            assert "data" in item
            assert len(item["data"]) > 0

    def test_results_are_parseable(self, multi_dat):
        results = split_dat_bytes(multi_dat)
        for item in results:
            re_parsed = parse_dat_controllers(item["data"])
            assert len(re_parsed) == 1  # each should be a single-controller DAT


class TestRearrangeAndConvertDatBytes:
    """Tests for rearrange_and_convert_dat_bytes."""

    def test_identity_rearrangement(self, sample_dat_bytes):
        """Empty orders dict — rearrange + convert to opposite type."""
        result = rearrange_and_convert_dat_bytes(sample_dat_bytes, {})
        assert isinstance(result, list)
        assert len(result) > 0
        item = result[0]
        assert "name" in item
        assert "controller" in item
        assert "data" in item
        assert isinstance(item["data"], bytes)
        assert len(item["data"]) > 0
        # Controller type should be opposite of the source
        controllers = parse_dat_controllers(sample_dat_bytes)
        src_type = controllers[0]["controller_type"]
        # item["controller"] should be the opposite
        assert item["controller"] != src_type or src_type not in {"AE-200", "AE-C400A", "EW-50", "EW-C50"}

    def test_result_is_parseable(self, sample_dat_bytes):
        result = rearrange_and_convert_dat_bytes(sample_dat_bytes, {})
        for item in result:
            re_parsed = parse_dat_controllers(item["data"])
            assert len(re_parsed) > 0
