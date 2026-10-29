# /// script
# requires-python = ">=3.10"
# dependencies = ["pycryptodome", "dnfile"]
# ///
"""Decrypt Heartopia's image cache (ScreenCapture) into plain JPEG/PNG files.

The game caches every image with AES-256-CBC. The key and IV are not stored here: they are
read at runtime from the static initializer of Client.BaseService.Utility.File.EncryptUtil
in your install's XDTBaseService.dll, after undoing its XDENCODE wrapper.

Default output:
    album/   photos you uploaded to the in-game album (normal+<you>+Album+<ts>)
    photos/  local camera photos, largest cached resolution per photo

With "all": every file under ScreenCapture, mirrored into all/<subfolder>/
with the extension fixed to the real format.

Usage: uv run decrypt_heartopia.py <out_dir> [all]
"""

import datetime
import functools
import os
import re
import struct
import sys
from pathlib import Path

import dnfile
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

HEARTOPIA_DIR = Path(
    "~/Library/Application Support/CrossOver/Bottles/Steam/drive_c/users/crossover"
    "/AppData/LocalLow/xd/Heartopia"
).expanduser()
SCREEN_DIR = HEARTOPIA_DIR / "ScreenCapture"
PHOTO_DIR = SCREEN_DIR / "Photo"


def xdencode_decode(data: bytes) -> bytes:
    """Undo XDENCODE0001: after a 20-byte header, word i = (plain ^ K) + (i % 32), K = u32 at 12."""
    (k,) = struct.unpack_from("<I", data, 12)
    body = data[20:]
    n = len(body) // 4
    words = struct.unpack_from(f"<{n}I", body)
    plain = struct.pack(f"<{n}I", *(((w - i % 32) & 0xFFFFFFFF) ^ k for i, w in enumerate(words)))
    return plain + body[4 * n :]


@functools.cache
def cipher_params() -> tuple[bytes, bytes]:
    """Read EncryptUtil's KEY and IV byte arrays from the installed XDTBaseService.dll."""
    pe = dnfile.dnPE(data=xdencode_decode((HEARTOPIA_DIR / "DotnetAssemblies" / "XDTBaseService.dll").read_bytes()))
    md, data = pe.net.mdtables, pe.__data__
    util = next(t for t in md.TypeDef.rows if t.TypeName == "EncryptUtil")
    cctor = next(m.row for m in util.MethodList if m.row.Name == ".cctor")
    off = pe.get_offset_from_rva(cctor.Rva)
    if data[off] & 3 == 2:
        body = data[off + 1 : off + 1 + (data[off] >> 2)]
    else:
        body = data[off + 12 : off + 12 + struct.unpack_from("<I", data, off + 4)[0]]
    rvas = {r.Field.row_index: r.Rva for r in md.FieldRva.rows}
    arrays = {}
    # C# array initializer: ldc.i4(.s) N; newarr byte; dup; ldtoken <data>; call InitializeArray; stsfld <field>
    for m in re.finditer(rb"(?:\x1f(.)|\x20(.{4}))\x8d.{4}\x25\xd0(.{4})\x28.{4}\x80(.{4})", body, re.S):
        size = m[1][0] if m[1] else struct.unpack("<i", m[2])[0]
        src = pe.get_offset_from_rva(rvas[struct.unpack("<I", m[3])[0] & 0xFFFFFF])
        name = str(md.Field.rows[(struct.unpack("<I", m[4])[0] & 0xFFFFFF) - 1].Name)
        arrays[name] = data[src : src + size]
    return arrays["KEY"], arrays["IV"]


def filetime(ts: int) -> datetime.datetime:
    """Convert a Windows FILETIME (100 ns ticks since 1601) to local time."""
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    return (epoch + datetime.timedelta(microseconds=ts // 10)).astimezone()


def decrypt(src: Path) -> bytes:
    """Return the plaintext of one cached file."""
    key, iv = cipher_params()
    return unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(src.read_bytes()), 16)


def decrypt_to(src: Path, dst: Path, ts: int) -> None:
    """Decrypt one cached file to dst and set its mtime to the photo time."""
    dst.write_bytes(decrypt(src))
    t = filetime(ts).timestamp()
    os.utime(dst, (t, t))


def dump_all(out: Path) -> None:
    """Decrypt every file under ScreenCapture into out/all/<subfolder>/, keeping names and mtimes."""
    for sub in sorted(p for p in SCREEN_DIR.iterdir() if p.is_dir()):
        dst_dir = out / "all" / sub.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        files = [f for f in sub.iterdir() if f.is_file()]
        for f in files:
            data = decrypt(f)
            ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
            dst = dst_dir / (f.name.removesuffix(".jpg").removesuffix(".png") + ext)
            dst.write_bytes(data)
            st = f.stat()
            os.utime(dst, (st.st_atime, st.st_mtime))
        print(f"all/{sub.name}: {len(files)} files")


def main(out: Path) -> None:
    """Pick the files to export and decrypt them into out/album and out/photos."""
    album: dict[int, tuple[int, Path]] = {}
    photos: dict[int, tuple[int, Path]] = {}
    for f in PHOTO_DIR.iterdir():
        if m := re.fullmatch(r"normal\+\w+\+Album\+(\d+)\.png_(\d+)_(\d+)\.jpg", f.name):
            bucket = album
        elif m := re.fullmatch(r"(\d+)_(\d+)_(\d+)\.jpg", f.name):
            bucket = photos
        else:
            continue
        ts, area = int(m[1]), int(m[2]) * int(m[3])
        if area > bucket.get(ts, (0, f))[0]:
            bucket[ts] = (area, f)

    for name, bucket in (("album", album), ("photos", photos)):
        (out / name).mkdir(parents=True, exist_ok=True)
        for ts, (_, src) in bucket.items():
            decrypt_to(src, out / name / f"{filetime(ts):%Y-%m-%d_%H-%M-%S}_{ts}.jpg", ts)
        print(f"{name}: {len(bucket)} files")


if __name__ == "__main__":
    if sys.argv[2:] == ["all"]:
        dump_all(Path(sys.argv[1]))
    else:
        main(Path(sys.argv[1]))
