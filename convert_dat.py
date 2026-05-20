"""
convert_dat.py  —  Convert an existing .dat file to a different controller type.

Usage:
    python convert_dat.py input.dat --to AE-C400A [output_dir]

The ControlGroup data (units, icons, names, areas) is preserved exactly.
All other sections come from the target controller's template, so the
structural differences between controller families are handled automatically.

output_dir defaults to the same folder as input.dat.
Output filename: "{SystemData Name} {controller}.dat"
"""

import argparse
import io
import os
import sys

import pyzipper
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

from lib.dat_utils import safe_filename
from lib.zipcrypto import build_dat_bytes, PASSWORD

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

EMPTY_CONFIGS = {
    "AE-C400A": os.path.join(SCRIPT_DIR, "Empty Configs", "AE-C400 Config Empty.dat"),
    "AE-200": os.path.join(SCRIPT_DIR, "Empty Configs", "AE-200 Config Empty.dat"),
    "EW-C50": os.path.join(SCRIPT_DIR, "Empty Configs", "EW-C50 Config Empty.dat"),
    "EW-50": os.path.join(SCRIPT_DIR, "Empty Configs", "EW-50 Config Empty.dat"),
}

# Data-bearing lists to carry over -- same meaning across all controller types
DATA_LISTS = {"MnetGroupList", "ViewInfoList", "MnetList", "AreaGroupList", "AreaList"}


# ---------------------------------------------------------------------------
# Conversion logic
# ---------------------------------------------------------------------------


def convert(input_path, target_controller, output_dir):
    template_path = os.path.join(SCRIPT_DIR, "templates", f"{target_controller}.xml")
    if not os.path.exists(template_path):
        print(f"ERROR: template not found: {template_path}")
        sys.exit(1)

    # Read source
    with pyzipper.AESZipFile(input_path) as z:
        src_xml = z.read("1", pwd=PASSWORD)

    src_root = ET.fromstring(src_xml)
    src_sd = src_root.find(".//SystemData")
    src_cg = src_root.find(".//ControlGroup")

    system_name = src_sd.get("Name", "")

    # Load target template
    tmpl_tree = ET.parse(template_path)
    tmpl_root = tmpl_tree.getroot()
    tmpl_sd = tmpl_root.find(".//SystemData")
    tmpl_cg = tmpl_root.find(".//ControlGroup")

    # 1. Set Name only in target SystemData
    tmpl_sd.set("Name", system_name)

    # 2. Rebuild target ControlGroup: keep target's structure,
    #    replace data lists with source content
    src_data = {child.tag: child for child in src_cg if child.tag in DATA_LISTS}

    for child in list(tmpl_cg):
        if child.tag in DATA_LISTS and child.tag in src_data:
            idx = list(tmpl_cg).index(child)
            tmpl_cg.remove(child)
            tmpl_cg.insert(idx, src_data[child.tag])

    # Serialize
    out = io.BytesIO()
    tmpl_tree.write(out, encoding="utf-8", xml_declaration=True)
    xml_bytes = out.getvalue()

    # Build ZIP entries from target empty config
    empty_dat = EMPTY_CONFIGS[target_controller]
    zip_entries = [("1", xml_bytes, True)]
    with pyzipper.AESZipFile(empty_dat) as z:
        available = z.namelist()
        if "NetworkSetting.xml" in available:
            zip_entries.append(
                ("NetworkSetting.xml", z.read("NetworkSetting.xml", pwd=PASSWORD), True)
            )
    if any(n.endswith("/") for n in available):
        zip_entries.append(("IMG/", None, False))

    # Output filename: "{Name} {controller}.dat"
    safe_name = safe_filename(system_name)
    out_filename = f"{safe_name} {target_controller}.dat"
    out_path = os.path.join(output_dir, out_filename)

    dat_bytes = build_dat_bytes(zip_entries)
    with open(out_path, "wb") as f:
        f.write(dat_bytes)

    groups = len(src_cg.findall(".//MnetRecord"))
    print(f"  '{system_name}' ({groups} groups) -> {out_filename}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Convert .dat between controller types")
    parser.add_argument("input", help="Input .dat file")
    parser.add_argument(
        "--to",
        required=True,
        dest="target",
        help=f"Target controller type: {', '.join(EMPTY_CONFIGS)}",
    )
    parser.add_argument(
        "output_dir", nargs="?", default=None, help="Output folder (default: same as input)"
    )
    args = parser.parse_args()

    if args.target not in EMPTY_CONFIGS:
        print(f"ERROR: unknown controller '{args.target}'. Choose from: {', '.join(EMPTY_CONFIGS)}")
        sys.exit(1)

    output_dir = args.output_dir or os.path.dirname(os.path.abspath(args.input))
    os.makedirs(output_dir, exist_ok=True)

    convert(args.input, args.target, output_dir)


if __name__ == "__main__":
    main()
