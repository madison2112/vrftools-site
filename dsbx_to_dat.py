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
import sys
import xml.etree.ElementTree as ET

import pyzipper

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

from lib.dat_utils import safe_filename, FAMILY_MAP
from lib.dsbx_utils import (
    _text,
    build_control_group,
    get_groupof50_list,
    parse_dsbx_bytes,
)
from lib.zipcrypto import build_dat_bytes, PASSWORD

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAP = os.path.join(SCRIPT_DIR, "dsbx_dat_mapping.json")
EMPTY_CONFIGS = {
    "AE-C400A": os.path.join(SCRIPT_DIR, "Empty Configs", "AE-C400 Config Empty.dat"),
    "AE-200": os.path.join(SCRIPT_DIR, "Empty Configs", "AE-200 Config Empty.dat"),
    "EW-C50": os.path.join(SCRIPT_DIR, "Empty Configs", "EW-C50 Config Empty.dat"),
    "EW-50": os.path.join(SCRIPT_DIR, "Empty Configs", "EW-50 Config Empty.dat"),
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Convert .dsbx to AE-C400 .dat")
    parser.add_argument("dsbx", help="Input .dsbx file")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Output folder (default: current directory). One .dat per Groupof50 block.",
    )
    parser.add_argument(
        "--controller",
        default="AE-C400A",
        help="Controller type (default: AE-C400A). Must match a file in templates/",
    )
    parser.add_argument("--mapping", default=DEFAULT_MAP, help="Path to mapping JSON")
    args = parser.parse_args()

    if args.controller not in EMPTY_CONFIGS:
        print(
            f"ERROR: unknown controller '{args.controller}'. Choose from: {', '.join(EMPTY_CONFIGS)}"
        )
        sys.exit(1)

    with open(args.mapping, encoding="utf-8") as f:
        mapping = json.load(f)

    with open(args.dsbx, "rb") as f:
        dsb_root = parse_dsbx_bytes(f.read())
    g50_list = get_groupof50_list(dsb_root)

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
            net_xml = (
                z.read("NetworkSetting.xml", pwd=PASSWORD)
                if "NetworkSetting.xml" in available
                else None
            )
        has_img = any(n.endswith("/") for n in available)

        # Load a fresh copy of the template for each block
        tmpl_tree = ET.parse(template_xml_path)
        tmpl_root = tmpl_tree.getroot()

        sd = tmpl_root.find(".//SystemData")
        sd.set("Name", _text(groupof50, "Name"))

        db = tmpl_root.find(".//DatabaseManager")
        old_cg = db.find("ControlGroup")
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

        dat_bytes = build_dat_bytes(entries)
        with open(out_path, "wb") as f:
            f.write(dat_bytes)

        groups = len(tmpl_root.findall(".//MnetRecord"))
        print(
            f"  [{block_controller}] '{_text(groupof50, 'Name')}' ({groups} groups) -> {os.path.basename(out_path)}"
        )


if __name__ == "__main__":
    main()
