"""Move moov atom to the front so browsers can start playback immediately."""
from __future__ import annotations

import struct
from pathlib import Path


def _boxes(data: bytes, start: int = 0, end: int | None = None):
    if end is None:
        end = len(data)
    i = start
    while i + 8 <= end:
        size = struct.unpack_from(">I", data, i)[0]
        typ = bytes(data[i + 4 : i + 8])
        hdr = 8
        if size == 1:
            if i + 16 > end:
                break
            size = struct.unpack_from(">Q", data, i + 8)[0]
            hdr = 16
        elif size == 0:
            size = end - i
        if size < hdr or i + size > end:
            break
        yield i, size, hdr, typ
        i += size


def _patch_offsets(moov: bytearray, delta: int) -> None:
    stack = [(0, len(moov))]
    while stack:
        start, end = stack.pop()
        for i, size, hdr, typ in _boxes(moov, start, end):
            if typ in {b"trak", b"mdia", b"minf", b"stbl", b"edts", b"moov"}:
                stack.append((i + hdr, i + size))
            elif typ == b"stco":
                count = struct.unpack_from(">I", moov, i + hdr + 4)[0]
                p = i + hdr + 8
                for n in range(count):
                    off = struct.unpack_from(">I", moov, p + n * 4)[0] + delta
                    struct.pack_into(">I", moov, p + n * 4, off)
            elif typ == b"co64":
                count = struct.unpack_from(">I", moov, i + hdr + 4)[0]
                p = i + hdr + 8
                for n in range(count):
                    off = struct.unpack_from(">Q", moov, p + n * 8)[0] + delta
                    struct.pack_into(">Q", moov, p + n * 8, off)


def faststart_bytes(data: bytes) -> bytes:
    boxes = list(_boxes(data))
    ftyp = next((b for b in boxes if b[3] == b"ftyp"), None)
    moov = next((b for b in boxes if b[3] == b"moov"), None)
    mdat = next((b for b in boxes if b[3] == b"mdat"), None)
    if not ftyp or not moov or not mdat:
        return data
    if moov[0] < mdat[0]:
        return data
    ftyp_blob = data[ftyp[0] : ftyp[0] + ftyp[1]]
    moov_blob = bytearray(data[moov[0] : moov[0] + moov[1]])
    mdat_blob = data[mdat[0] : mdat[0] + mdat[1]]
    new_mdat = len(ftyp_blob) + len(moov_blob)
    _patch_offsets(moov_blob, new_mdat - mdat[0])
    rest = [
        data[i : i + size]
        for i, size, _, typ in boxes
        if typ not in {b"ftyp", b"moov", b"mdat"}
    ]
    return b"".join([ftyp_blob, bytes(moov_blob), *rest, mdat_blob])


def faststart_file(path: Path) -> bool:
    raw = path.read_bytes()
    out = faststart_bytes(raw)
    if out == raw:
        return False
    tmp = path.with_suffix(path.suffix + ".fast")
    tmp.write_bytes(out)
    tmp.replace(path)
    return True
