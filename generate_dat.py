"""
generate_dat.py  --  AE-C400 configuration .dat generator

Usage:
    python generate_dat.py groups.csv output.dat

Reads group settings from a CSV and produces an AE-C400 .dat config file
that can be imported by ISToolAEC.exe.

CSV columns: group_number, mnet_address, group_name

The .dat file is a ZipCrypto-encrypted ZIP (password: MELCO) containing:
  1               -- main XML config
  NetworkSetting.xml -- network/cloud settings (unchanged from template)
  IMG/            -- empty directory marker
"""

import csv
import os
import sys

import pyzipper

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

from lib.zipcrypto import build_dat_bytes, PASSWORD

TEMPLATE = os.path.join(os.path.dirname(__file__), "AE-C400 Config Empty.dat")


# ---------------------------------------------------------------------------
# XML manipulation
# ---------------------------------------------------------------------------


def load_template_xml():
    with pyzipper.AESZipFile(TEMPLATE) as z:
        return z.read("1", pwd=PASSWORD), z.read("NetworkSetting.xml", pwd=PASSWORD)


def build_xml(xml_bytes, groups):
    """
    groups: list of (group_number:int, mnet_address:int, group_name:str)
    Returns modified XML as UTF-8 bytes.
    """
    import io
    import xml.etree.ElementTree as ET

    ET.register_namespace("", "")
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()

    cg = root.find(".//ControlGroup")

    for tag, records in [
        (
            "MnetGroupList",
            [
                {"Group": str(g), "Address": str(a), "Model": "IC", "SubModel": ""}
                for g, a, _ in groups
            ],
        ),
        ("MnetList", [{"Group": str(g), "GroupNameWeb": name} for g, _, name in groups]),
        ("ViewInfoList", [{"Group": str(g), "Icon": "0"} for g, _, _ in groups]),
    ]:
        elem = cg.find(tag)
        elem.clear()
        elem.tag = tag
        record_tag = tag.replace("List", "Record")
        for attrs in records:
            child = ET.SubElement(elem, record_tag)
            for k, v in attrs.items():
                child.set(k, v)

    out = io.BytesIO()
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) != 3:
        print("Usage: python generate_dat.py groups.csv output.dat")
        sys.exit(1)

    csv_path, output_path = sys.argv[1], sys.argv[2]

    groups = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            groups.append((int(row["group_number"]), int(row["mnet_address"]), row["group_name"]))
    print(f"Loaded {len(groups)} groups from {csv_path}")

    xml_bytes, net_xml = load_template_xml()
    new_xml = build_xml(xml_bytes, groups)
    print(f"XML built ({len(new_xml)} bytes)")

    dat_bytes = build_dat_bytes(
        [
            ("1", new_xml, True),
            ("NetworkSetting.xml", net_xml, True),
            ("IMG/", None, False),
        ]
    )
    with open(output_path, "wb") as f:
        f.write(dat_bytes)
    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
