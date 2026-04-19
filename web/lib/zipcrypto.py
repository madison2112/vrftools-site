"""
ZipCrypto (PKWARE traditional encryption) writer.
Produces byte-compatible output with the ISToolAEC .dat format.
Password for all DAT files: b"MELCO"
"""
import io
import os
import struct
import time
import zlib

PASSWORD = b"MELCO"

# ---------------------------------------------------------------------------
# CRC / key stream
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_dat_bytes(entries):
    """
    Build a ZipCrypto-encrypted DAT and return the raw bytes.

    entries: list of (name_str, data_bytes_or_None, encrypt_bool)
      data=None  → empty directory entry (e.g. "IMG/")
      encrypt=True → ZipCrypto-encrypt the entry
    """
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
            eh, ed = _encrypt(compressed, PASSWORD, crc)
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

    return buf.getvalue()
