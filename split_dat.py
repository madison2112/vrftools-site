"""
split_dat.py  --  Extract each controller from a multi-controller AE-200 .dat file
                 into its own standalone .dat file.

Usage:
    python split_dat.py input.dat [output_folder]

output_folder defaults to the same directory as input.dat.

A multi-controller .dat ZIP contains entries like:
  1       -- AE-200A master controller
  1-1     -- EW-50 expansion #1 (slaved to AE-200)
  1-2     -- EW-50 expansion #2
  2       -- standalone EW-50

Each XML entry is re-encrypted as its own ZipCrypto .dat file named after
the SystemData/@Name field. The IMG/ directory entry is included in each output.
"""

import io
import os
import sys

import pyzipper

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

from lib.dat_utils import safe_filename
from lib.zipcrypto import build_dat_bytes, PASSWORD


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: python split_dat.py input.dat [output_folder]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(input_path))
    os.makedirs(output_dir, exist_ok=True)

    import xml.etree.ElementTree as ET

    with pyzipper.AESZipFile(input_path) as z:
        all_entries = z.namelist()

        # XML entries: anything that doesn't contain '/' (not a directory or sub-path)
        xml_entries = [e for e in all_entries if "/" not in e]

        print(f"Found {len(xml_entries)} controller entries: {xml_entries}")

        for entry in xml_entries:
            xml_bytes = z.read(entry, pwd=PASSWORD)

            # Read controller name from SystemData
            try:
                root = ET.fromstring(xml_bytes)
                sd = root.find(".//SystemData")
                ctrl_name = sd.get("Name", entry) if sd is not None else entry
                model = sd.get("Model", "unknown") if sd is not None else "unknown"
                groups = len(root.findall(".//MnetRecord"))
            except ET.ParseError as e:
                print(f"  [{entry}] XML parse error: {e} -- skipping")
                continue

            filename = safe_filename(ctrl_name) + ".dat"
            out_path = os.path.join(output_dir, filename)

            # Each standalone DAT just needs "1" + "IMG/"
            dat_bytes = build_dat_bytes(
                [
                    ("1", xml_bytes, True),
                    ("IMG/", None, False),
                ]
            )
            with open(out_path, "wb") as f:
                f.write(dat_bytes)

            print(f"  [{entry}] {model} | '{ctrl_name}' | {groups} groups -> {filename}")


if __name__ == "__main__":
    main()
