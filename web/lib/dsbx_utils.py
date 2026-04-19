"""
DSBX parsing and DAT XML generation.
Ported from dsbx_to_dat.py with bytes-in / ET.Element-out interface.
"""
import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET

REPO_ROOT    = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TEMPLATES_DIR = os.path.join(REPO_ROOT, "templates")
DEFAULT_MAP  = os.path.join(REPO_ROOT, "dsbx_dat_mapping.json")

FAMILY_MAP = {
    "AE-C400A": {"AE": "AE-C400A", "EW": "EW-C50"},
    "AE-200":   {"AE": "AE-200",   "EW": "EW-50"},
}

# Which controllers include optional ZIP entries
NEEDS_IMG     = {"AE-C400A", "EW-C50", "EW-50"}
NEEDS_NETWORK = {"AE-C400A", "EW-C50"}


def load_mapping():
    with open(DEFAULT_MAP, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Helpers (same logic as dsbx_to_dat.py)
# ---------------------------------------------------------------------------

def _text(elem, tag, default=""):
    c = elem.find(tag) if elem is not None else None
    return c.text if c is not None and c.text else default


def _valid_mnet(addr):
    if not addr or addr.strip().upper() in ("N/A", "NA", ""):
        return False
    try:
        int(addr)
        return True
    except ValueError:
        return False


def _build_indices(groupof50):
    assoc_to_idus   = {}
    group_to_system = {}

    for system in groupof50.findall("System"):
        ou = system.find("OutdoorUnit")
        if ou is None:
            continue
        odu_mnet = _text(ou, "MNetAddress")
        if not _valid_mnet(odu_mnet):
            continue

        bc   = ou.find("BCController")
        idus = bc.findall("IndoorUnit") if bc is not None else ou.findall("IndoorUnit")

        for idu in idus:
            mnet = _text(idu, "MNetAddress")
            if not _valid_mnet(mnet):
                continue
            assoc = _text(idu, "AssociatedIndoorUnitGroup")
            if not assoc:
                continue
            assoc_to_idus.setdefault(assoc, []).append({
                "mnet":     mnet,
                "model":    _text(idu, "ModelNumber"),
                "ref_tag":  _text(idu, "ReferenceTag"),
                "odu_mnet": odu_mnet,
                "system":   system,
            })
            group_to_system[assoc] = system

    lossnay_index = {}
    for lossnay in groupof50.findall("Lossnay"):
        lg_id = _text(lossnay, "LossnayGroupId")
        if lg_id:
            lossnay_index[lg_id] = lossnay

    return assoc_to_idus, lossnay_index, group_to_system


def lookup_icon(model_number, rules, default_icon):
    for rule in rules:
        pattern        = rule["pattern"]
        case_sensitive = rule.get("case_sensitive", True)
        target = model_number if case_sensitive else model_number.upper()
        pat    = pattern      if case_sensitive else pattern.upper()
        if rule["match"] == "contains"   and pat in target:          return rule["icon"]
        if rule["match"] == "startswith" and target.startswith(pat): return rule["icon"]
    return default_icon


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dsbx_bytes(data: bytes) -> ET.Element:
    """Unzip a .dsbx and return the root XML element."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return ET.fromstring(z.read("xml").decode("utf-8-sig"))


def get_groupof50_list(dsb_root: ET.Element):
    project = dsb_root.find("Project")
    if project is None:
        raise ValueError("No <Project> element found in .dsbx file")
    return project.findall("Groupof50")


def build_control_group(groupof50: ET.Element, mapping: dict) -> ET.Element:
    """Build the <ControlGroup> XML element from a Groupof50 DSB block."""
    icon_rules   = mapping["icon_rules"]
    default_icon = mapping["default_icon"]

    assoc_to_idus, lossnay_index, group_to_system = _build_indices(groupof50)

    all_iugs = groupof50.findall("IndoorUnitGroup")
    groups = []
    for iug in all_iugs:
        tid   = _text(iug, "TableId")
        gtype = _text(iug, "GroupType")
        gnum  = _text(iug, "GroupNumber")
        if gtype == "IU"      and not assoc_to_idus.get(tid):       continue
        if gtype == "Lossnay" and lossnay_index.get(tid) is None:   continue
        groups.append((int(gnum), gtype, tid, iug))
    groups.sort(key=lambda x: x[0])

    valid_systems = [s for s in groupof50.findall("System")
                     if _valid_mnet(_text(s.find("OutdoorUnit"), "MNetAddress"))]
    system_area = {id(s): i for i, s in enumerate(valid_systems, start=1)}

    group_area = {}
    for gnum, gtype, tid, iug in groups:
        if gtype == "IU":
            sys_elem = group_to_system.get(tid)
            if sys_elem is not None:
                group_area[gnum] = system_area.get(id(sys_elem))
        elif gtype == "Lossnay":
            group_area[gnum] = len(valid_systems) + 1

    cg = ET.Element("ControlGroup")
    ET.SubElement(cg, "McList")

    mgl = ET.SubElement(cg, "MnetGroupList")
    for gnum, gtype, tid, iug in groups:
        gstr = str(gnum)
        if gtype == "IU":
            for rec in assoc_to_idus.get(tid, []):
                model = "AIC" if rec["mnet"] == rec["odu_mnet"] else "IC"
                ET.SubElement(mgl, "MnetGroupRecord",
                    Group=gstr, Address=rec["mnet"], Model=model, SubModel="")
            rc = iug.find("LocalRemoteController")
            if rc is not None and rc.find("MNetAddress") is not None:
                ET.SubElement(mgl, "MnetGroupRecord",
                    Group=gstr, Address=_text(rc, "MNetAddress"), Model="RC", SubModel="")
        elif gtype == "Lossnay":
            lossnay = lossnay_index[tid]
            ET.SubElement(mgl, "MnetGroupRecord",
                Group=gstr, Address=_text(lossnay, "MNetAddress"), Model="LC", SubModel="")

    ET.SubElement(cg, "DdcInfoList")

    vil = ET.SubElement(cg, "ViewInfoList")
    for gnum, gtype, tid, iug in groups:
        if gtype == "IU":
            idus = assoc_to_idus.get(tid, [])
            icon = lookup_icon(idus[0]["model"] if idus else "", icon_rules, default_icon)
        else:
            icon = 0
        ET.SubElement(vil, "ViewInfoRecord", Group=str(gnum), Icon=str(icon))

    mnl = ET.SubElement(cg, "MnetList")
    for gnum, gtype, tid, iug in groups:
        if gtype == "IU":
            idus = assoc_to_idus.get(tid, [])
            name = idus[0]["ref_tag"] if idus else ""
        else:
            lossnay = lossnay_index[tid]
            name = _text(lossnay, "ReferenceTag")
        ET.SubElement(mnl, "MnetRecord", Group=str(gnum), GroupNameWeb=name)

    ET.SubElement(cg, "InterlockList")

    agl = ET.SubElement(cg, "AreaGroupList")
    max_area = len(valid_systems) + (1 if any(gt == "Lossnay" for _, gt, _, _ in groups) else 0)
    for area_num in range(1, max_area + 1):
        for gnum, gtype, tid, iug in groups:
            if group_area.get(gnum) == area_num:
                ET.SubElement(agl, "AreaGroupRecord",
                    Area=str(area_num), Group=str(gnum), ModelID="MNET")

    al = ET.SubElement(cg, "AreaList")
    for i, sys_elem in enumerate(valid_systems, start=1):
        ET.SubElement(al, "AreaRecord",
            Area=str(i), AreaName=_text(sys_elem, "SystemName"))
    if any(gt == "Lossnay" for _, gt, _, _ in groups):
        ET.SubElement(al, "AreaRecord",
            Area=str(len(valid_systems) + 1), AreaName="ERVs")

    for tag in ("OcNameList", "McNameList", "ModbusList"):
        ET.SubElement(cg, tag)

    return cg


def extract_group_cards(groupof50: ET.Element, mapping: dict) -> list:
    """
    Return a list of group card dicts for the frontend rearrangement UI.
    [{"slot": 1, "tag": "Floor-01", "mnet_addresses": ["50"], "unit_types": ["IC"], "icon": 10}, ...]
    """
    icon_rules   = mapping["icon_rules"]
    default_icon = mapping["default_icon"]
    assoc_to_idus, lossnay_index, _ = _build_indices(groupof50)

    cards = []
    for iug in groupof50.findall("IndoorUnitGroup"):
        tid   = _text(iug, "TableId")
        gtype = _text(iug, "GroupType")
        gnum  = _text(iug, "GroupNumber")

        if gtype == "IU":
            idus = assoc_to_idus.get(tid, [])
            if not idus:
                continue
            mnets      = [r["mnet"] for r in idus]
            unit_types = ["AIC" if r["mnet"] == r["odu_mnet"] else "IC" for r in idus]
            tag        = idus[0]["ref_tag"]
            icon       = lookup_icon(idus[0]["model"], icon_rules, default_icon)
            rc = iug.find("LocalRemoteController")
            if rc is not None and rc.find("MNetAddress") is not None:
                mnets.append(_text(rc, "MNetAddress"))
                unit_types.append("RC")
        elif gtype == "Lossnay":
            lossnay = lossnay_index.get(tid)
            if lossnay is None:
                continue
            mnets      = [_text(lossnay, "MNetAddress")]
            unit_types = ["LC"]
            tag        = _text(lossnay, "ReferenceTag")
            icon       = 0
        else:
            continue

        cards.append({
            "slot":          int(gnum),
            "tag":           tag,
            "mnet_addresses": mnets,
            "unit_types":    unit_types,
            "icon":          icon,
        })

    cards.sort(key=lambda c: c["slot"])
    return cards


def dsbx_to_dat_bytes(dsbx_data: bytes, target_family: str = "AE-C400A") -> list:
    """
    Convert a .dsbx to one or more .dat files.
    target_family: "AE-C400A" (default) or "AE-200"

    Returns list of {"name": str, "controller": str, "data": bytes}
    """
    from .zipcrypto import build_dat_bytes

    mapping   = load_mapping()
    dsb_root  = parse_dsbx_bytes(dsbx_data)
    g50_list  = get_groupof50_list(dsb_root)
    family    = FAMILY_MAP.get(target_family, FAMILY_MAP["AE-C400A"])

    results = []
    for groupof50 in g50_list:
        src_model = _text(groupof50.find("SystemRemoteController"), "ModelNumber") or ""
        controller = family["EW"] if src_model.upper().startswith("EW") else family["AE"]

        template_path = os.path.join(TEMPLATES_DIR, f"{controller}.xml")
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")

        tmpl_tree = ET.parse(template_path)
        tmpl_root = tmpl_tree.getroot()

        sd = tmpl_root.find(".//SystemData")
        if sd is not None:
            sd.set("Name", _text(groupof50, "Name"))

        db     = tmpl_root.find(".//DatabaseManager")
        old_cg = db.find("ControlGroup")
        idx    = list(db).index(old_cg)
        db.remove(old_cg)
        db.insert(idx, build_control_group(groupof50, mapping))

        out_buf = io.BytesIO()
        tmpl_tree.write(out_buf, encoding="utf-8", xml_declaration=True)
        xml_bytes = out_buf.getvalue()

        entries = [("1", xml_bytes, True)]
        net_path = os.path.join(TEMPLATES_DIR, f"NetworkSetting-{controller}.xml")
        if controller in NEEDS_NETWORK and os.path.exists(net_path):
            with open(net_path, "rb") as nf:
                entries.append(("NetworkSetting.xml", nf.read(), True))
        if controller in NEEDS_IMG:
            entries.append(("IMG/", None, False))

        safe_name = _text(groupof50, "Name")
        for ch in r'\/:*?"<>|':
            safe_name = safe_name.replace(ch, "_")

        results.append({
            "name":       f"{safe_name} {controller}",
            "controller": controller,
            "data":       build_dat_bytes(entries),
        })

    return results
