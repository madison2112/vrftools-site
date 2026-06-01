"""
DAT file operations: parse, convert, split, rearrange.
All functions accept/return bytes for the web context.
"""

import copy
import io
import os
import re
import xml.etree.ElementTree as ET

import pyzipper

from .zipcrypto import PASSWORD, build_dat_bytes

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATES_DIR = os.path.join(REPO_ROOT, "templates")

DATA_LISTS = {"MnetGroupList", "ViewInfoList", "MnetList", "AreaGroupList", "AreaList"}

CONTROLLER_REGISTRY = {
    "AE-200": {
        "opposite": "AE-C400A",
        "family_ae": "AE-200",
        "family_ew": "EW-50",
        "needs_img": False,
        "needs_network": False,
    },
    "AE-C400A": {
        "opposite": "AE-200",
        "family_ae": "AE-C400A",
        "family_ew": "EW-C50",
        "needs_img": True,
        "needs_network": True,
    },
    "EW-50": {
        "opposite": "EW-C50",
        "family_ae": "AE-200",
        "family_ew": "EW-50",
        "needs_img": True,
        "needs_network": False,
    },
    "EW-C50": {
        "opposite": "EW-50",
        "family_ae": "AE-C400A",
        "family_ew": "EW-C50",
        "needs_img": True,
        "needs_network": True,
    },
}

# Derived convenience aliases for backward compatibility
OPPOSITE = {k: v["opposite"] for k, v in CONTROLLER_REGISTRY.items()}
NEEDS_IMG = {k for k, v in CONTROLLER_REGISTRY.items() if v["needs_img"]}
NEEDS_NETWORK = {k for k, v in CONTROLLER_REGISTRY.items() if v["needs_network"]}
FAMILY_MAP = {
    k: {"AE": v["family_ae"], "EW": v["family_ew"]}
    for k, v in CONTROLLER_REGISTRY.items()
    if k in ("AE-C400A", "AE-200")
}


# Maps Model attribute prefixes (uppercased) to canonical controller types.
# AE-50 and EW-50 are the same physical device (regional rebrand); both map to EW-50.
MODEL_PREFIX_MAP = [
    ("AE-200",   "AE-200"),
    ("AE200",    "AE-200"),
    ("AE-C400",  "AE-C400A"),
    ("AE-C400A", "AE-C400A"),
    ("AE-C50",   "EW-C50"),
    ("AEC50",    "EW-C50"),
    ("EW-C50",   "EW-C50"),
    ("EWC50",    "EW-C50"),
    ("EW-50",    "EW-50"),
    ("EW50",     "EW-50"),
    ("AE-50",    "EW-50"),
    ("AE50",     "EW-50"),
]


def _model_to_ctrl_type(model: str, has_network: bool, has_img: bool) -> str:
    """Resolve controller type from Model attribute, falling back to ZIP structure flags."""
    m = model.upper()
    for prefix, ctrl_type in MODEL_PREFIX_MAP:
        if m.startswith(prefix):
            return ctrl_type
    # Fall back to file-level structure detection
    if has_network:
        return "EW-C50" if m.startswith("EW") else "AE-C400A"
    if has_img:
        return "EW-50"
    return "AE-200"


def safe_filename(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "unnamed"


def _open_dat(dat_bytes: bytes):
    """Return an open pyzipper.AESZipFile from bytes."""
    return pyzipper.AESZipFile(io.BytesIO(dat_bytes))


def detect_controller_type(dat_bytes: bytes) -> str:
    """
    Detect controller type from ZIP structure and XML content.
    Returns one of: AE-200, AE-C400A, EW-50, EW-C50
    """
    with _open_dat(dat_bytes) as z:
        names = z.namelist()
        has_network = "NetworkSetting.xml" in names
        has_img = any(n.endswith("/") for n in names)
        xml_bytes = z.read("1", pwd=PASSWORD)

    root = ET.fromstring(xml_bytes)
    sd = root.find(".//SystemData")
    model = (sd.get("Model", "") if sd is not None else "").upper()
    return _model_to_ctrl_type(model, has_network, has_img)


def parse_dat_controllers(dat_bytes: bytes) -> list:
    """
    Extract all controller XML entries from a (possibly multi-controller) DAT.
    Returns list of {"entry": str, "name": str, "controller_type": str, "ip": str, "xml_bytes": bytes}

    Multi-controller DATs use entries like "1", "1-1", "1-2", "2" — the hyphenated
    entries are EW-50/AE-50 expansion controllers subordinate to their main controller.
    Entries are returned sorted so expansions immediately follow their parent (1, 1-1, 1-2, 2).
    """
    with _open_dat(dat_bytes) as z:
        names = z.namelist()
        has_network = "NetworkSetting.xml" in names
        has_img = any(n.endswith("/") for n in names)
        xml_entries = sorted(
            [e for e in names if re.match(r"^\d+(-\d+)*$", e)],
            key=lambda s: tuple(int(x) for x in s.split("-")),
        )

        controllers = []
        for entry in xml_entries:
            xml_bytes = z.read(entry, pwd=PASSWORD)
            try:
                root = ET.fromstring(xml_bytes)
                sd = root.find(".//SystemData")
                name = sd.get("Name", entry) if sd is not None else entry
                model = (sd.get("Model", "") if sd is not None else "").upper()
                ip = sd.get("IPAdrsLan", "") if sd is not None else ""
            except ET.ParseError:
                continue

            controllers.append(
                {
                    "entry": entry,
                    "name": name,
                    "controller_type": _model_to_ctrl_type(model, has_network, has_img),
                    "ip": ip,
                    "xml_bytes": xml_bytes,
                }
            )

    return controllers


def extract_groups_from_xml(xml_bytes: bytes) -> list:
    """
    Parse ControlGroup XML and return group card data for the frontend.
    [{"slot": 1, "tag": "Floor-01", "mnet_addresses": ["50"], "unit_types": ["IC"], "icon": 10}]
    """
    root = ET.fromstring(xml_bytes)
    cg = root.find(".//ControlGroup")
    if cg is None:
        return []

    mnet_records = {}
    for r in cg.findall(".//MnetGroupRecord"):
        g = int(r.get("Group", 0))
        mnet_records.setdefault(g, []).append(
            {
                "address": r.get("Address", ""),
                "model": r.get("Model", ""),
            }
        )

    names = {int(r.get("Group", 0)): r.get("GroupNameWeb", "") for r in cg.findall(".//MnetRecord")}

    icons = {int(r.get("Group", 0)): int(r.get("Icon", 0)) for r in cg.findall(".//ViewInfoRecord")}

    cards = []
    for slot in sorted(set(list(mnet_records.keys()) + list(names.keys()))):
        recs = mnet_records.get(slot, [])
        cards.append(
            {
                "slot": slot,
                "tag": names.get(slot, ""),
                "mnet_addresses": [r["address"] for r in recs],
                "unit_types": [r["model"] for r in recs],
                "icon": icons.get(slot, 0),
            }
        )

    return cards


def _check_warnings(cards: list) -> dict:
    """Check for sequential M-Net correlation and unsorted tag names (IC units only)."""
    sequential = (
        all(
            c["slot"] == int(c["mnet_addresses"][0])
            for c in cards
            if c["mnet_addresses"] and c["unit_types"] and c["unit_types"][0] in ("IC", "AIC", "??")
        )
        if cards
        else False
    )

    ic_tags = [c["tag"] for c in cards if c["unit_types"] and c["unit_types"][0] in ("IC", "AIC", "??")]
    unsorted = ic_tags != sorted(ic_tags) if len(ic_tags) > 1 else False

    return {"sequential_mnet": sequential, "unsorted_tags": unsorted}


def generate_dat_bytes(xml_bytes: bytes, controller_type: str) -> bytes:
    """
    Wrap XML bytes in a properly structured, encrypted DAT ZIP.
    """
    entries = [("1", xml_bytes, True)]
    net_path = os.path.join(TEMPLATES_DIR, f"NetworkSetting-{controller_type}.xml")
    if controller_type in NEEDS_NETWORK and os.path.exists(net_path):
        with open(net_path, "rb") as f:
            entries.append(("NetworkSetting.xml", f.read(), True))
    if controller_type in NEEDS_IMG:
        entries.append(("IMG/", None, False))
    return build_dat_bytes(entries)


def convert_dat_bytes(dat_bytes: bytes) -> list:
    """
    Convert each controller in the DAT to its opposite family type.
    Returns list of {"name": str, "controller": str, "data": bytes}
    """
    controllers = parse_dat_controllers(dat_bytes)
    results = []

    for ctrl in controllers:
        src_type = ctrl["controller_type"]
        tgt_type = OPPOSITE.get(src_type, src_type)
        template_path = os.path.join(TEMPLATES_DIR, f"{tgt_type}.xml")
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")

        src_root = ET.fromstring(ctrl["xml_bytes"])
        src_sd = src_root.find(".//SystemData")
        src_cg = src_root.find(".//ControlGroup")
        sys_name = src_sd.get("Name", "") if src_sd is not None else ""

        tmpl_tree = ET.parse(template_path)
        tmpl_root = tmpl_tree.getroot()
        tmpl_sd = tmpl_root.find(".//SystemData")
        tmpl_cg = tmpl_root.find(".//ControlGroup")

        if tmpl_sd is not None:
            tmpl_sd.set("Name", sys_name)

        src_data = {child.tag: child for child in src_cg if child.tag in DATA_LISTS}
        for child in list(tmpl_cg):
            if child.tag in DATA_LISTS and child.tag in src_data:
                idx = list(tmpl_cg).index(child)
                tmpl_cg.remove(child)
                tmpl_cg.insert(idx, src_data[child.tag])

        out_buf = io.BytesIO()
        tmpl_tree.write(out_buf, encoding="utf-8", xml_declaration=True)

        results.append(
            {
                "name": f"{safe_filename(sys_name)} {tgt_type}",
                "controller": tgt_type,
                "data": generate_dat_bytes(out_buf.getvalue(), tgt_type),
            }
        )

    return results


def split_dat_bytes(dat_bytes: bytes) -> list:
    """
    Split a multi-controller DAT into individual DATs.
    Returns list of {"name": str, "controller": str, "data": bytes}
    """
    controllers = parse_dat_controllers(dat_bytes)
    if len(controllers) < 2:
        raise ValueError("DAT file contains only one controller — nothing to split.")

    results = []
    for ctrl in controllers:
        results.append(
            {
                "name": safe_filename(ctrl["name"]),
                "controller": ctrl["controller_type"],
                "data": generate_dat_bytes(ctrl["xml_bytes"], ctrl["controller_type"]),
            }
        )
    return results


def apply_rearrangement(xml_bytes: bytes, new_order: list) -> bytes:
    """
    Rewrite ControlGroup XML with remapped group slot numbers.

    new_order: list of old slot numbers in their desired new positions.
    e.g. [3, 1, 2] means: old slot 3 → new slot 1, old slot 1 → new slot 2, etc.
    Slots not listed are appended in their original order at the end.
    """
    root = ET.fromstring(xml_bytes)
    cg = root.find(".//ControlGroup")
    if cg is None:
        return xml_bytes

    # Build slot→index mapping: position in new_order (1-indexed) becomes the new
    # Group number for that old slot.  Zeros represent empty positions and are skipped
    # so gaps are preserved (e.g. groups at old slots 1-10 and 19 keep the gap).
    old_to_new = {old_slot: pos + 1 for pos, old_slot in enumerate(new_order) if old_slot > 0}

    for elem in cg.iter():
        val = elem.get("Group")
        if val is not None:
            try:
                old_slot = int(val)
                if old_slot in old_to_new:
                    elem.set("Group", str(old_to_new[old_slot]))
            except ValueError:
                pass

    # ISToolAEC writes (and expects) records in ascending Group-number order within
    # each list.  After remapping attributes the physical order is wrong — sort each
    # list that uses Group as its primary key so the file stays compatible.
    _GROUP_LISTS = {"MnetGroupList", "ViewInfoList", "MnetList"}
    for child in cg:
        if child.tag in _GROUP_LISTS:
            child[:] = sorted(child, key=lambda e: int(e.get("Group", 0)))

    out = io.BytesIO()
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    return out.getvalue()


def rearrange_dat_bytes(dat_bytes: bytes, new_order: list) -> bytes:
    """
    Parse a single-controller DAT, apply group rearrangement, and return new DAT bytes.
    new_order: list of old slot numbers in desired new position order.
    """
    controllers = parse_dat_controllers(dat_bytes)
    if not controllers:
        raise ValueError("Could not parse DAT file.")
    if len(controllers) > 1:
        raise ValueError("Rearrangement requires a single-controller DAT.")

    ctrl = controllers[0]
    new_xml = apply_rearrangement(ctrl["xml_bytes"], new_order)
    return generate_dat_bytes(new_xml, ctrl["controller_type"])


def rearrange_and_repackage_dat_bytes(dat_bytes: bytes, orders: dict) -> bytes:
    """
    Apply per-controller rearrangements and repackage as a single .dat
    (multi-controller format preserved; single-controller returns standard .dat).
    orders: {block_idx: [old_slot, ...]}
    """
    controllers = parse_dat_controllers(dat_bytes)
    entries = []
    for i, ctrl in enumerate(controllers):
        order = orders.get(i)
        xml = apply_rearrangement(ctrl["xml_bytes"], order) if order else ctrl["xml_bytes"]
        entries.append((ctrl["entry"], xml, True))

    with _open_dat(dat_bytes) as z:
        ctrl_entry_names = {c["entry"] for c in controllers}
        for name in z.namelist():
            if name in ctrl_entry_names:
                continue
            if name.endswith("/"):
                entries.append((name, None, False))
            else:
                try:
                    data = z.read(name, pwd=PASSWORD)
                except Exception:
                    data = z.read(name)
                entries.append((name, data, True))

    return build_dat_bytes(entries)


def rearrange_and_split_dat_bytes(dat_bytes: bytes, orders: dict) -> list:
    """
    Apply per-controller rearrangements and split into individual per-controller .dat files.
    Returns list of {"name": str, "controller": str, "data": bytes}.
    """
    controllers = parse_dat_controllers(dat_bytes)
    results = []
    for i, ctrl in enumerate(controllers):
        order = orders.get(i)
        xml = apply_rearrangement(ctrl["xml_bytes"], order) if order else ctrl["xml_bytes"]
        results.append(
            {
                "name": safe_filename(ctrl["name"]),
                "controller": ctrl["controller_type"],
                "data": generate_dat_bytes(xml, ctrl["controller_type"]),
            }
        )
    return results


def rearrange_and_convert_dat_bytes(dat_bytes: bytes, orders: dict) -> list:
    """
    Apply per-controller rearrangements, split, and convert each to its opposite generation.
    Returns list of {"name": str, "controller": str, "data": bytes}.
    """
    controllers = parse_dat_controllers(dat_bytes)
    results = []
    for i, ctrl in enumerate(controllers):
        order = orders.get(i)
        xml = apply_rearrangement(ctrl["xml_bytes"], order) if order else ctrl["xml_bytes"]

        src_type = ctrl["controller_type"]
        tgt_type = OPPOSITE.get(src_type, src_type)
        template_path = os.path.join(TEMPLATES_DIR, f"{tgt_type}.xml")
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")

        src_root = ET.fromstring(xml)
        src_sd = src_root.find(".//SystemData")
        src_cg = src_root.find(".//ControlGroup")
        sys_name = src_sd.get("Name", "") if src_sd is not None else ""

        tmpl_tree = ET.parse(template_path)
        tmpl_root = tmpl_tree.getroot()
        tmpl_sd = tmpl_root.find(".//SystemData")
        tmpl_cg = tmpl_root.find(".//ControlGroup")

        if tmpl_sd is not None:
            tmpl_sd.set("Name", sys_name)
        if src_cg is not None and tmpl_cg is not None:
            src_data = {child.tag: child for child in src_cg if child.tag in DATA_LISTS}
            for child in list(tmpl_cg):
                if child.tag in DATA_LISTS and child.tag in src_data:
                    idx = list(tmpl_cg).index(child)
                    tmpl_cg.remove(child)
                    tmpl_cg.insert(idx, src_data[child.tag])

        out_buf = io.BytesIO()
        tmpl_tree.write(out_buf, encoding="utf-8", xml_declaration=True)
        results.append(
            {
                "name": f"{safe_filename(sys_name)} {tgt_type}",
                "controller": tgt_type,
                "data": generate_dat_bytes(out_buf.getvalue(), tgt_type),
            }
        )
    return results


def sort_groups_by_tag(cards: list) -> list:
    """
    Return a new_order list that sorts IC/AIC groups by tag name using natural
    sort (IDU-1, IDU-2, IDU-10, IDU-11 — not IDU-1, IDU-10, IDU-11, IDU-2).
    LC groups follow, preserving internal order within each category.
    """
    def _natural_key(s):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s)]

    ic_slots = [c["slot"] for c in cards if c["unit_types"] and c["unit_types"][0] in ("IC", "AIC", "??")]
    lc_slots = [c["slot"] for c in cards if c["unit_types"] and c["unit_types"][0] == "LC"]
    other = [c["slot"] for c in cards if c["slot"] not in ic_slots and c["slot"] not in lc_slots]

    ic_sorted = sorted(
        ic_slots, key=lambda s: _natural_key(next((c["tag"] for c in cards if c["slot"] == s), ""))
    )

    return ic_sorted + other + lc_slots


_STRIP_FOR_EXPANSION = {"Web", "EneBlock", "Apportion"}


def build_multi_dat_200(controllers: list) -> bytes:
    """
    Package 200-series controllers into a single multi-controller .dat file.

    controllers: list of dicts with:
      entry     — ZIP entry name: "1", "1-1", "2", etc.
      xml_bytes — XML with user edits already applied
      ip        — IP address string (written to SystemData/@IPAdrsLan)

    Main entries (no "-"): ControlAeList AeNo updated to match the assigned
    entry number; Web/EneBlock/Apportion kept intact.
    Expansion entries ("-" present): Web, EneBlock, and Apportion stripped.
    IMG/ and per-entry IMG/<entry>/ directories are added automatically.
    """
    entries = []

    for ctrl in controllers:
        entry = ctrl["entry"]
        xml = ctrl["xml_bytes"]
        ip = ctrl.get("ip", "")
        is_expansion = "-" in entry
        ae_no = int(entry.split("-")[0])

        try:
            root = ET.fromstring(xml)
            db = root.find(".//DatabaseManager")
            if db is not None:
                sd = db.find("SystemData")
                if sd is not None and ip:
                    sd.set("IPAdrsLan", ip)

                if is_expansion:
                    for child in list(db):
                        if child.tag in _STRIP_FOR_EXPANSION:
                            db.remove(child)
                else:
                    # Update ControlAeList: self-reference only (v8.03 format)
                    for web_elem in db.findall("Web"):
                        cae_list = web_elem.find("ControlAeList")
                        if cae_list is not None:
                            for rec in cae_list.findall("ControlAeRecord"):
                                rec.set("AeNo", str(ae_no))

            buf = io.BytesIO()
            ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
            xml = buf.getvalue()
        except ET.ParseError:
            pass

        entries.append((entry, xml, True))

    # Add IMG/ root and one subdirectory per controller entry
    entries.append(("IMG/", None, False))
    for c in sorted(controllers, key=lambda c: tuple(int(x) for x in c["entry"].split("-"))):
        entries.append((f"IMG/{c['entry']}/", None, False))

    return build_dat_bytes(entries)


def build_multi_dat_400(controllers: list) -> bytes:
    """
    Package 400-series controllers into a single multi-controller .dat file.

    controllers: list of dicts with:
      entry     — ZIP entry name: "1", "2", ...
      xml_bytes — XML with user edits already applied
      ip        — IP address string
      is_master — bool (BACnet master → TotalMaster="ON" in ScSystem)

    ScSystem is updated in every entry with the full network topology.
    NetworkSetting.xml is generated with one <Item> per controller.
    """
    entries = []

    for ctrl in controllers:
        entry = ctrl["entry"]
        xml = ctrl["xml_bytes"]
        ip = ctrl.get("ip", "")

        try:
            root = ET.fromstring(xml)
            db = root.find(".//DatabaseManager")
            if db is not None:
                sd = db.find("SystemData")
                if sd is not None and ip:
                    sd.set("IPAdrsLan", ip)

                new_sc = ET.Element("ScSystem")
                sc_list = ET.SubElement(new_sc, "ScSystemDataList")
                for other in controllers:
                    is_self = other["entry"] == entry
                    ET.SubElement(
                        sc_list, "ScSystemDataRecord",
                        ScNo=other["entry"],
                        HostName="" if is_self else (other.get("ip") or ""),
                        TotalMaster="ON" if other.get("is_master") else "OFF",
                        Apportion="OFF",
                    )

                old_sc = db.find("ScSystem")
                if old_sc is not None:
                    idx = list(db).index(old_sc)
                    db.remove(old_sc)
                    db.insert(idx, new_sc)
                else:
                    db.append(new_sc)

            buf = io.BytesIO()
            ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
            xml = buf.getvalue()
        except ET.ParseError:
            pass

        entries.append((entry, xml, True))

    entries.append(("NetworkSetting.xml", _build_400_network_setting(len(controllers)), True))
    return build_dat_bytes(entries)


def _build_400_network_setting(count: int) -> bytes:
    """Clone the single-controller NetworkSetting template to produce N items."""
    net_template_path = os.path.join(TEMPLATES_DIR, "NetworkSetting-AE-C400A.xml")
    tree = ET.parse(net_template_path)
    root = tree.getroot()
    items_el = root.find("Items")
    base_item = items_el.find("Item")
    items_el.clear()
    for i in range(count):
        item = copy.deepcopy(base_item)
        cc_no_el = item.find("CcNo")
        if cc_no_el is not None:
            cc_no_el.text = str(i + 1)
        items_el.append(item)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def apply_group_names(xml_bytes: bytes, tag_map: dict) -> bytes:
    """
    Apply edited group tag names to an XML document.
    tag_map: {old_slot: new_tag_name} where slot is int
    Returns updated XML bytes, or original if nothing changed.
    """
    if not tag_map:
        return xml_bytes

    root = ET.fromstring(xml_bytes)
    cg = root.find(".//ControlGroup")
    if cg is None:
        return xml_bytes

    for record in cg.findall(".//MnetRecord"):
        group = record.get("Group")
        if group and int(group) in tag_map:
            record.set("GroupNameWeb", tag_map[int(group)])

    out = io.BytesIO()
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    return out.getvalue()
