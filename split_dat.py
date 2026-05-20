"""
split_dat.py  —  Extract each controller from a multi-controller AE-200 .dat file
                 into its own standalone .dat file.

Usage:
    python split_dat.py input.dat [output_folder]

output_folder defaults to the same directory as input.dat.

A multi-controller .dat ZIP contains entries like:
  1       — AE-200A master controller
  1-1     — EW-50 expansion #1 (slaved to AE-200)
  1-2     — EW-50 expansion #2
  2       — standalone EW-50

Each XML entry is re-encrypted as its own ZipCrypto .dat file named after
the SystemData/@Name field. The IMG/ directory entry is included in each output.
"""

import io
import os
import struct
import sys
import zlib

import pyzipper

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "lib"))

PASSWORD = b"MELCO"


# ---------------------------------------------------------------------------
# ZipCrypto writer (same implementation as dsbx_to_dat.py)
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

        nb2 = nb
        buf.write(struct.pack("<4s5H3I2H",
            b"PK\x03\x04", 20, 0x0001 if enc else 0, 8, dt, dd,
            crc & 0xFFFFFFFF, len(payload), len(data), len(nb2), 0) + nb2)
        buf.write(payload)
        cds.append(struct.pack("<4s6H3I5HII",
            b"PK\x01\x02", 20, 20, 0x0001 if enc else 0, 8, dt, dd,
            crc & 0xFFFFFFFF, len(payload), len(data),
            len(nb2), 0, 0, 0, 0, 0, off) + nb2)

    cd_off = buf.tell()
    cd = b"".join(cds)
    buf.write(cd)
    buf.write(struct.pack("<4s4H2IH",
        b"PK\x05\x06", 0, 0, len(cds), len(cds), len(cd), cd_off, 0))

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def safe_filename(name):
    """Strip characters that are invalid in Windows filenames."""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "unnamed"


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
                model     = sd.get("Model", "unknown") if sd is not None else "unknown"
                groups    = len(root.findall(".//MnetRecord"))
            except ET.ParseError as e:
                print(f"  [{entry}] XML parse error: {e} — skipping")
                continue

            filename = safe_filename(ctrl_name) + ".dat"
            out_path = os.path.join(output_dir, filename)

            # Each standalone DAT just needs "1" + "IMG/"
            write_zipcrypto(out_path, [
                ("1",    xml_bytes, True),
                ("IMG/", None,      False),
            ], PASSWORD)

            print(f"  [{entry}] {model} | '{ctrl_name}' | {groups} groups -> {filename}")


if __name__ == "__main__":
    main()
