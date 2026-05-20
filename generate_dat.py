"""
generate_dat.py  —  AE-C400 configuration .dat generator

Usage:
    python generate_dat.py groups.csv output.dat

Reads group settings from a CSV and produces an AE-C400 .dat config file
that can be imported by ISToolAEC.exe.

CSV columns: group_number, mnet_address, group_name

The .dat file is a ZipCrypto-encrypted ZIP (password: MELCO) containing:
  1               — main XML config
  NetworkSetting.xml — network/cloud settings (unchanged from template)
  IMG/            — empty directory marker
"""

import csv
import io
import os
import struct
import sys
import zlib
import xml.etree.ElementTree as ET

import pyzipper

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))

TEMPLATE = os.path.join(os.path.dirname(__file__), "AE-C400 Config Empty.dat")
PASSWORD = b"MELCO"


# ---------------------------------------------------------------------------
# ZipCrypto writer (pure Python, stdlib only)
# Produces traditional PKWARE encryption identical to the original .dat files
# ---------------------------------------------------------------------------


def _make_crc_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            if c & 1:
                c = 0xEDB88320 ^ (c >> 1)
            else:
                c >>= 1
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
    """Return (encryption_header_12_bytes, encrypted_data_bytes)."""
    keys = _init_keys(password)
    # 12-byte random header; last byte must equal high byte of CRC-32
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


def _dos_time(ts=None):
    """Return (dos_time, dos_date) for the given time.time() value (or now)."""
    import time

    t = time.localtime(ts)
    dos_time = (t.tm_sec // 2) | (t.tm_min << 5) | (t.tm_hour << 11)
    dos_date = t.tm_mday | (t.tm_mon << 5) | ((t.tm_year - 1980) << 9)
    return dos_time, dos_date


def _local_file_header(
    name_bytes, compressed_size, uncompressed_size, crc, dos_time, dos_date, encrypted=True
):
    flags = 0x0001 if encrypted else 0x0000
    return (
        struct.pack(
            "<4s5H3I2H",
            b"PK\x03\x04",  # signature
            20,  # version needed (2.0)
            flags,  # general purpose bit flags
            8,  # compression method: Deflate
            dos_time,
            dos_date,
            crc & 0xFFFFFFFF,
            compressed_size,
            uncompressed_size,
            len(name_bytes),
            0,  # extra field length
        )
        + name_bytes
    )


def _central_dir_entry(
    name_bytes, compressed_size, uncompressed_size, crc, dos_time, dos_date, offset, encrypted=True
):
    flags = 0x0001 if encrypted else 0x0000
    return (
        struct.pack(
            "<4s6H3I5HII",
            b"PK\x01\x02",  # signature
            20,  # version made by
            20,  # version needed
            flags,  # general purpose bit flags
            8,  # compression: Deflate
            dos_time,
            dos_date,
            crc & 0xFFFFFFFF,
            compressed_size,
            uncompressed_size,
            len(name_bytes),
            0,  # extra field length
            0,  # file comment length
            0,  # disk number start
            0,  # internal attributes
            0,  # external attributes
            offset,  # relative offset of local header
        )
        + name_bytes
    )


def _end_of_central_dir(num_entries, cd_size, cd_offset):
    return struct.pack(
        "<4s4H2IH",
        b"PK\x05\x06",
        0,
        0,  # disk number, disk with start of CD
        num_entries,
        num_entries,
        cd_size,
        cd_offset,
        0,  # comment length
    )


def write_zipcrypto(output_path, entries, password):
    """
    entries: list of (name_str, data_bytes, encrypted_bool)
    Writes a ZipCrypto-encrypted ZIP to output_path.
    """
    buf = io.BytesIO()
    cd_entries = []
    dt, dd = _dos_time()

    for name, data, encrypt in entries:
        name_bytes = name.encode("utf-8")
        offset = buf.tell()

        if data is None:
            # Directory entry
            lh = (
                struct.pack(
                    "<4s5H3I2H",
                    b"PK\x03\x04",
                    20,
                    0,
                    0,
                    dt,
                    dd,
                    0,
                    0,
                    0,
                    len(name_bytes),
                    0,
                )
                + name_bytes
            )
            buf.write(lh)
            cd = (
                struct.pack(
                    "<4s6H3I5HII",
                    b"PK\x01\x02",
                    20,
                    20,
                    0,
                    0,
                    dt,
                    dd,
                    0,
                    0,
                    0,
                    len(name_bytes),
                    0,
                    0,
                    0,
                    0,
                    0x10,
                    offset,
                )
                + name_bytes
            )
            cd_entries.append(cd)
            continue

        compressed = zlib.compress(data, 9)[2:-4]  # strip zlib header/trailer
        crc = zlib.crc32(data) & 0xFFFFFFFF

        if encrypt:
            enc_hdr, enc_data = _encrypt(compressed, password, crc)
            payload = enc_hdr + enc_data
        else:
            payload = compressed

        lh = _local_file_header(name_bytes, len(payload), len(data), crc, dt, dd, encrypt)
        buf.write(lh)
        buf.write(payload)

        cd = _central_dir_entry(name_bytes, len(payload), len(data), crc, dt, dd, offset, encrypt)
        cd_entries.append(cd)

    cd_offset = buf.tell()
    cd_data = b"".join(cd_entries)
    buf.write(cd_data)
    buf.write(_end_of_central_dir(len(cd_entries), len(cd_data), cd_offset))

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())


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

    write_zipcrypto(
        output_path,
        [
            ("1", new_xml, True),
            ("NetworkSetting.xml", net_xml, True),
            ("IMG/", None, False),
        ],
        PASSWORD,
    )
    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
