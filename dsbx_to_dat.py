"""
dsbx_to_dat.py  —  Convert a Mitsubishi Electric .dsbx design file to an AE-C400 .dat config file

Usage:
    python dsbx_to_dat.py input.dsbx output.dat [--controller AE-C400A]

--controller defaults to AE-C400A. The corresponding template XML must exist in the
templates/ folder (e.g. templates/AE-C400A.xml). That file is the single source of truth
for all static sections (SystemData defaults, ScSystem, Web, Apportion, etc.) — only
SystemData/@Name and <ControlGroup> are replaced from DSB data.

Edit dsbx_dat_mapping.json to correct icon mappings without touching this file.
"""

import argparse
import io
import json
import os
import struct
import sys
import zipfile
import zlib
import xml.etree.ElementTree as ET

import pyzipper

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

from lib.dat_utils import safe_filename

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAP = os.path.join(SCRIPT_DIR, "dsbx_dat_mapping.json")
EMPTY_CONFIGS = {
    "AE-C400A": os.path.join(SCRIPT_DIR, "Empty Configs", "AE-C400 Config Empty.dat"),
    "AE-200":   os.path.join(SCRIPT_DIR, "Empty Configs", "AE-200 Config Empty.dat"),
    "EW-C50":   os.path.join(SCRIPT_DIR, "Empty Configs", "EW-C50 Config Empty.dat"),
    "EW-50":    os.path.join(SCRIPT_DIR, "Empty Configs", "EW-50 Config Empty.dat"),
}

# When --controller is a primary type (AE-C400A or AE-200), EW-type DSB blocks
# are automatically mapped to the equivalent EW controller for that tool family.
FAMILY_MAP = {
    "AE-C400A": {"AE": "AE-C400A", "EW": "EW-C50"},
    "AE-200":   {"AE": "AE-200",   "EW": "EW-50"},
}
PASSWORD = b"MELCO"


# ---------------------------------------------------------------------------
# ZipCrypto writer
# ---------------------------------------------------------------------------

def _make_crc_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = 0xEDB88320 ^ (c >> 1) if c & 1 else c >> 1
        table.append(c)
    return table

_CRC_TABLE = _make_crc_table()

def _crc32_byte(crc, byte):
    return _CRC_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)

def _init_keys(password):
    k = [0x12345678, 0x23456789, 0x34567890]
    for b in password:
        _update_keys(k, b)
    return k

def _update_keys(k, byte):
    k[0] = _crc32_byte(k[0], byte)
    k[1] = (k[1] + (k[0] & 0xFF)) & 0xFFFFFFFF
    k[1] = (k[1] * 134775813 + 1) & 0xFFFFFFFF
    k[2] = _crc32_byte(k[2], (k[1] >> 24) & 0xFF)

def _stream_byte(k):
    t = (k[2] | 2) & 0xFFFF
    return ((t * (t ^ 1)) >> 8) & 0xFF

def _encrypt(data, password, crc32_val):
    keys = _init_keys(password)
    header = bytearray(os.urandom(11)) + bytearray([(crc32_val >> 24) & 0xFF])
    enc_header = bytearray(12)
    for i, b in enumerate(header):
        enc_header[i] = _stream_byte(keys) ^ b
        _update_keys(keys, b)
    enc_data = bytearray(len(data))
    for i, b in enumerate(data):
        enc_data[i] = _stream_byte(keys) ^ b
        _update_keys(keys, b)
    return bytes(enc_header), bytes(enc_data)

def _dos_time():
    import time
    t = time.localtime()
    return (
        (t.tm_sec // 2) | (t.tm_min << 5) | (t.tm_hour << 11),
        t.tm_mday | (t.tm_mon << 5) | ((t.tm_year - 1980) << 9),
    )

def _lfh(name_b, comp, uncomp, crc, dt, dd, enc):
    return struct.pack("<4s5H3I2H",
        b"PK\x03\x04", 20, 0x0001 if enc else 0, 8, dt, dd,
        crc & 0xFFFFFFFF, comp, uncomp, len(name_b), 0) + name_b

def _cde(name_b, comp, uncomp, crc, dt, dd, offset, enc):
    return struct.pack("<4s6H3I5HII",
        b"PK\x01\x02", 20, 20, 0x0001 if enc else 0, 8, dt, dd,
        crc & 0xFFFFFFFF, comp, uncomp,
        len(name_b), 0, 0, 0, 0, 0, offset) + name_b

def write_zipcrypto(output_path, entries, password):
    """entries: list of (name_str, data_bytes_or_None, encrypt_bool)"""
    buf = io.BytesIO()
    cds = []
    dt, dd = _dos_time()

    for name, data, enc in entries:
        nb = name.encode("utf-8")
        off = buf.tell()

        if data is None:
            buf.write(struct.pack("<4s5H3I2H",
                b"PK\x03\x04", 20, 0, 0, dt, dd, 0, 0, 0, len(nb), 0) + nb)
            cds.append(struct.pack("<4s6H3I5HII",
                b"PK\x01\x02", 20, 20, 0, 0, dt, dd, 0, 0, 0,
                len(nb), 0, 0, 0, 0, 0x10, off) + nb)
            continue

        compressed = zlib.compress(data, 9)[2:-4]
        crc = zlib.crc32(data) & 0xFFFFFFFF
        if enc:
            eh, ed = _encrypt(compressed, password, crc)
            payload = eh + ed
        else:
            payload = compressed

        buf.write(_lfh(nb, len(payload), len(data), crc, dt, dd, enc))
        buf.write(payload)
        cds.append(_cde(nb, len(payload), len(data), crc, dt, dd, off, enc))

    cd_off = buf.tell()
    cd = b"".join(cds)
    buf.write(cd)
    buf.write(struct.pack("<4s4H2IH",
        b"PK\x05\x06", 0, 0, len(cds), len(cds), len(cd), cd_off, 0))

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())


# ---------------------------------------------------------------------------
# Icon lookup
# ---------------------------------------------------------------------------

def lookup_icon(model_number, rules, default_icon):
    for rule in rules:
        pattern = rule["pattern"]
        case_sensitive = rule.get("case_sensitive", True)
        target = model_number if case_sensitive else model_number.upper()
        pat    = pattern     if case_sensitive else pattern.upper()
        if rule["match"] == "contains"   and pat in target:       return rule["icon"]
        if rule["match"] == "startswith" and target.startswith(pat): return rule["icon"]
    return default_icon


# ---------------------------------------------------------------------------
# DSB parsing helpers
# ---------------------------------------------------------------------------

def parse_dsbx(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read("xml").decode("utf-8-sig"))

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
    """
    Returns:
      assoc_to_idus  : {IndoorUnitGroup.TableId -> [idu_dict, ...]} (document order, valid MNet only)
      lossnay_index  : {LossnayGroupId -> Lossnay element}
      group_to_system: {IndoorUnitGroup.TableId -> System element}
    """
    assoc_to_idus   = {}
    group_to_system = {}

    for system in groupof50.findall("System"):
        ou = system.find("OutdoorUnit")
        if ou is None:
            continue
        odu_mnet = _text(ou, "MNetAddress")
        if not _valid_mnet(odu_mnet):
            continue  # skip non-M-Net systems (e.g. mini-splits with N/A address)

        idus = ou.findall(".//IndoorUnit")

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


# ---------------------------------------------------------------------------
# ControlGroup builder
# ---------------------------------------------------------------------------

def build_control_group(groupof50, mapping):
    icon_rules   = mapping["icon_rules"]
    default_icon = mapping["default_icon"]

    assoc_to_idus, lossnay_index, group_to_system = _build_indices(groupof50)

    # Collect valid groups only — IU groups need at least one valid IDU,
    # Lossnay groups need a matching Lossnay element
    all_iugs = groupof50.findall("IndoorUnitGroup")
    groups = []
    for iug in all_iugs:
        tid   = _text(iug, "TableId")
        gtype = _text(iug, "GroupType")
        gnum  = _text(iug, "GroupNumber")
        if gtype == "IU" and not assoc_to_idus.get(tid):
            continue  # no valid IDUs — skip (e.g. non-M-Net mini-split groups)
        if gtype == "Lossnay" and lossnay_index.get(tid) is None:
            continue
        groups.append((int(gnum), gtype, tid, iug))
    groups.sort(key=lambda x: x[0])

    # Area mapping: only systems with valid ODU M-Net addresses
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

    # Build the element
    cg = ET.Element("ControlGroup")
    ET.SubElement(cg, "McList")

    # MnetGroupList
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

    # ViewInfoList
    vil = ET.SubElement(cg, "ViewInfoList")
    for gnum, gtype, tid, iug in groups:
        if gtype == "IU":
            idus = assoc_to_idus.get(tid, [])
            icon = lookup_icon(idus[0]["model"] if idus else "", icon_rules, default_icon)
        else:
            icon = 0
        ET.SubElement(vil, "ViewInfoRecord", Group=str(gnum), Icon=str(icon))

    # MnetList
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

    # AreaGroupList / AreaList
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert .dsbx to AE-C400 .dat")
    parser.add_argument("dsbx",    help="Input .dsbx file")
    parser.add_argument("output_dir", nargs="?", default=None,
                        help="Output folder (default: current directory). One .dat per Groupof50 block.")
    parser.add_argument("--controller", default="AE-C400A",
                        help="Controller type (default: AE-C400A). Must match a file in templates/")
    parser.add_argument("--mapping", default=DEFAULT_MAP, help="Path to mapping JSON")
    args = parser.parse_args()

    if args.controller not in EMPTY_CONFIGS:
        print(f"ERROR: unknown controller '{args.controller}'. Choose from: {', '.join(EMPTY_CONFIGS)}")
        sys.exit(1)

    with open(args.mapping, encoding="utf-8") as f:
        mapping = json.load(f)

    dsb_root = parse_dsbx(args.dsbx)
    project  = dsb_root.find("Project")
    g50_list = project.findall("Groupof50")

    out_dir = args.output_dir or "."
    os.makedirs(out_dir, exist_ok=True)

    print(f"Found {len(g50_list)} controller block(s) in DSB.")

    for groupof50 in g50_list:
        # Resolve per-block controller type: EW-type DSB blocks get the EW
        # equivalent when a primary family type (AE-C400A / AE-200) is selected.
        family = FAMILY_MAP.get(args.controller)
        if family is not None:
            src_model = _text(groupof50.find("SystemRemoteController"), "ModelNumber") or ""
            block_controller = family["EW"] if src_model.upper().startswith("EW") else family["AE"]
        else:
            block_controller = args.controller

        template_xml_path = os.path.join(SCRIPT_DIR, "templates", f"{block_controller}.xml")
        empty_dat = EMPTY_CONFIGS[block_controller]
        with pyzipper.AESZipFile(empty_dat) as z:
            available = z.namelist()
            net_xml   = z.read("NetworkSetting.xml", pwd=PASSWORD) if "NetworkSetting.xml" in available else None
        has_img = any(n.endswith("/") for n in available)

        # Load a fresh copy of the template for each block
        tmpl_tree = ET.parse(template_xml_path)
        tmpl_root = tmpl_tree.getroot()

        sd = tmpl_root.find(".//SystemData")
        sd.set("Name", _text(groupof50, "Name"))

        db       = tmpl_root.find(".//DatabaseManager")
        old_cg   = db.find("ControlGroup")
        cg_index = list(db).index(old_cg)
        db.remove(old_cg)
        db.insert(cg_index, build_control_group(groupof50, mapping))

        out_buf = io.BytesIO()
        tmpl_tree.write(out_buf, encoding="utf-8", xml_declaration=True)
        xml_bytes = out_buf.getvalue()

        entries = [("1", xml_bytes, True)]
        if net_xml is not None:
            entries.append(("NetworkSetting.xml", net_xml, True))
        if has_img:
            entries.append(("IMG/", None, False))

        safe_name = safe_filename(_text(groupof50, "Name"))
        out_path = os.path.join(out_dir, f"{safe_name} {block_controller}.dat")

        write_zipcrypto(out_path, entries, PASSWORD)
        groups = len(tmpl_root.findall(".//MnetRecord"))
        print(f"  [{block_controller}] '{_text(groupof50, 'Name')}' ({groups} groups) -> {os.path.basename(out_path)}")


if __name__ == "__main__":
    main()
