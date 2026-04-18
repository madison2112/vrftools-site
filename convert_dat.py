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
import struct
import sys
import zlib

import pyzipper
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PASSWORD   = b"MELCO"

EMPTY_CONFIGS = {
    "AE-C400A": os.path.join(SCRIPT_DIR, "Testing files", "Empty Configs", "AE-C400 Config Empty.dat"),
    "AE-200":   os.path.join(SCRIPT_DIR, "Testing files", "Empty Configs", "AE-200 Config Empty.dat"),
    "EW-C50":   os.path.join(SCRIPT_DIR, "Testing files", "Empty Configs", "EW-C50 Config Empty.dat"),
    "EW-50":    os.path.join(SCRIPT_DIR, "Testing files", "Empty Configs", "EW-50 Config Empty.dat"),
}

# Data-bearing lists to carry over — same meaning across all controller types
DATA_LISTS = {"MnetGroupList", "ViewInfoList", "MnetList",
              "AreaGroupList", "AreaList"}


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

def write_zipcrypto(output_path, entries, password):
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

        buf.write(struct.pack("<4s5H3I2H",
            b"PK\x03\x04", 20, 0x0001 if enc else 0, 8, dt, dd,
            crc & 0xFFFFFFFF, len(payload), len(data), len(nb), 0) + nb)
        buf.write(payload)
        cds.append(struct.pack("<4s6H3I5HII",
            b"PK\x01\x02", 20, 20, 0x0001 if enc else 0, 8, dt, dd,
            crc & 0xFFFFFFFF, len(payload), len(data),
            len(nb), 0, 0, 0, 0, 0, off) + nb)

    cd_off = buf.tell()
    cd = b"".join(cds)
    buf.write(cd)
    buf.write(struct.pack("<4s4H2IH",
        b"PK\x05\x06", 0, 0, len(cds), len(cds), len(cd), cd_off, 0))

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())


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
    src_sd   = src_root.find(".//SystemData")
    src_cg   = src_root.find(".//ControlGroup")

    system_name = src_sd.get("Name", "")

    # Load target template
    tmpl_tree = ET.parse(template_path)
    tmpl_root = tmpl_tree.getroot()
    tmpl_sd   = tmpl_root.find(".//SystemData")
    tmpl_cg   = tmpl_root.find(".//ControlGroup")

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
            zip_entries.append(("NetworkSetting.xml",
                                z.read("NetworkSetting.xml", pwd=PASSWORD), True))
    if any(n.endswith("/") for n in available):
        zip_entries.append(("IMG/", None, False))

    # Output filename: "{Name} {controller}.dat"
    safe_name = system_name
    for ch in r'\/:*?"<>|':
        safe_name = safe_name.replace(ch, "_")
    out_filename = f"{safe_name} {target_controller}.dat"
    out_path = os.path.join(output_dir, out_filename)

    write_zipcrypto(out_path, zip_entries, PASSWORD)

    groups = len(src_cg.findall(".//MnetRecord"))
    print(f"  '{system_name}' ({groups} groups) -> {out_filename}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert .dat between controller types")
    parser.add_argument("input", help="Input .dat file")
    parser.add_argument("--to", required=True, dest="target",
                        help=f"Target controller type: {', '.join(EMPTY_CONFIGS)}")
    parser.add_argument("output_dir", nargs="?", default=None,
                        help="Output folder (default: same as input)")
    args = parser.parse_args()

    if args.target not in EMPTY_CONFIGS:
        print(f"ERROR: unknown controller '{args.target}'. Choose from: {', '.join(EMPTY_CONFIGS)}")
        sys.exit(1)

    output_dir = args.output_dir or os.path.dirname(os.path.abspath(args.input))
    os.makedirs(output_dir, exist_ok=True)

    convert(args.input, args.target, output_dir)


if __name__ == "__main__":
    main()
