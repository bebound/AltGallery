#!/usr/bin/env python3
"""Extract the app icon from an .ipa (iOS app archive).

Use this when the app has no icon in the repo and nothing usable in the
project's README/assets — it guarantees the *real* shipping artwork, at the
identifier the app actually ships with (see tools/ipa_bundle_id.py for that).

Candidates come from the app bundle's Info.plist icon keys (`CFBundleIcons` →
`CFBundlePrimaryIcon` → `CFBundleIconFiles`, the `~ipad` variant, and the
legacy `CFBundleIconFiles`), matched against the bundle's loose image files
(`<Entry>@2x.png`, `<Entry>@3x.png`, `<Entry>~ipad.png`, …), plus any
`*icon*.png` as a safety net. **The largest candidate wins** (by pixels, then
file size). The winner is written untouched — store icons are flat square
artwork; tools/render_news.py applies the rounded mask when it draws.

⚠️ Modern ipas usually ship only small loose icons — `AppIcon60x60@2x.png`
(120x120) and `AppIcon76x76@2x~ipad.png` (152x152) — while the 1024x1024
artwork lives in `Assets.car`, which is **not readable here**: it holds LZFSE
(`bvx2`)-compressed raw pixels, not images, and no PNG signature at all (there
is no stdlib LZFSE decoder; `assetutil` only lists renditions, it cannot
extract). A 152px icon is a last resort for the gallery — prefer the project's
own icon when it has one, and check the extracted size (reported on stderr).

Apple ships many icons as **CgBI** PNGs (iPhone-optimized: BGRA channel order,
premultiplied alpha, raw-deflate IDAT). Pillow cannot read them ("broken data
stream"); this script decodes them in pure Python and writes a standard PNG, so
the result is directly usable by Pillow (render_news.py) — no `sips` needed.
Standard PNGs and JPEGs are copied byte-for-byte.

Usage:
  tools/ipa_icon.py App.ipa                          # -> ./icon.png
  tools/ipa_icon.py App.ipa --out apps/Foo/icon.png   # where the gallery keeps it
  tools/ipa_icon.py App.ipa --list                    # just list the candidates
  tools/ipa_icon.py App.ipa --out icon.png --force    # overwrite an existing file

Stdout is the written path alone, so it stays scriptable; everything else goes
to stderr. Exit code: 0 on success, 1 when the ipa has no usable icon, the
output exists and `--force` was not given, or the file cannot be read.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
import zipfile
from pathlib import Path

from ipa_bundle_id import IpaError, find_main_app

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Icon entries in Info.plist carry no scale/dimension suffix ("AppIcon60x60");
# the files on disk do ("AppIcon60x60@2x.png", "AppIcon76x76@2x~ipad.png").
ICON_SUFFIX = re.compile(r"[@~-].*$")
ICON_NAME_HINT = re.compile(r"icon", re.IGNORECASE)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


class IconError(IpaError):
    """An ipa whose app icon cannot be extracted."""


def _icon_entries(info: dict) -> list[str]:
    """The icon base names named by the app's Info.plist."""
    entries: list[str] = []
    for key in ("CFBundleIcons", "CFBundleIcons~ipad"):
        icons = info.get(key)
        if isinstance(icons, dict):
            primary = icons.get("CFBundlePrimaryIcon")
            if isinstance(primary, dict):
                files = primary.get("CFBundleIconFiles")
                if isinstance(files, list):
                    entries += [str(name) for name in files]
    # Legacy keys (pre-iOS 5, and still written by some toolchains).
    for key in ("CFBundleIconFiles", "CFBundleIconFile"):
        value = info.get(key)
        if isinstance(value, str):
            entries.append(value)
        elif isinstance(value, list):
            entries += [str(name) for name in value]
    return entries


def _png_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a PNG's IHDR, without decoding the image."""
    offset = data.find(b"IHDR")
    if offset < 0 or len(data) < offset + 12:
        raise IconError("malformed PNG (no IHDR)")
    width, height = struct.unpack(">II", data[offset + 4 : offset + 12])
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's start-of-frame marker, skipping segments."""
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no payload
            offset += 2
            continue
        (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return width, height
        offset += 2 + length
    raise IconError("malformed JPEG (no start-of-frame)")


def _is_cgbi(data: bytes) -> bool:
    """Apple's iPhone-optimized PNG, marked by a CgBI chunk before IHDR."""
    return data[:64].find(b"CgBI") >= 0


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _unfilter(raw: bytes, width: int, height: int, channels: int) -> list[bytes]:
    """Undo the standard PNG row filters (0-4) on raw scanlines."""
    stride = width * channels
    rows: list[bytes] = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset : offset + stride])
        offset += stride
        if len(line) != stride:
            raise IconError("truncated image data")
        if filter_type == 0:  # None
            pass
        elif filter_type == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                up_left = previous[i - channels] if i >= channels else 0
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                if pa <= pb and pa <= pc:
                    predict = left
                elif pb <= pc:
                    predict = up
                else:
                    predict = up_left
                line[i] = (line[i] + predict) & 0xFF
        else:
            raise IconError(f"unsupported PNG filter type {filter_type}")
        rows.append(bytes(line))
        previous = line
    return rows


def decode_cgbi(data: bytes) -> bytes:
    """Decode a CgBI PNG into standard PNG bytes.

    CgBI differs from stock PNG three ways: the IDAT stream is *raw* deflate
    (no zlib header), channels are stored BGRA instead of RGBA, and color is
    premultiplied by alpha. Undo all three, then re-emit a plain PNG that any
    decoder (Pillow included) can read.
    """
    header: bytes | None = None
    idat = bytearray()
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        if offset + 12 + length > len(data):
            raise IconError(f"truncated CgBI PNG ({kind!r} chunk)")
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length  # length + type + payload + crc
        if kind == b"IHDR":
            header = payload
        elif kind == b"IDAT":
            idat += payload
        elif kind == b"IEND":
            break
    if header is None:
        raise IconError("CgBI PNG without an IHDR chunk")
    if not idat:
        raise IconError("CgBI PNG without image data")

    width, height, depth, color_type = struct.unpack(">IIBB", header[:10])
    if depth != 8:
        raise IconError(f"unsupported CgBI bit depth {depth} (only 8-bit)")
    if len(header) > 12 and header[12]:
        raise IconError("unsupported interlaced CgBI PNG")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise IconError(f"unsupported CgBI color type {color_type}")

    try:
        raw = zlib.decompressobj(-15).decompress(bytes(idat))
    except zlib.error as exc:
        raise IconError(f"cannot inflate CgBI data: {exc}") from exc
    rows = _unfilter(raw, width, height, channels)

    decoded = bytearray()
    for line in rows:
        pixel = bytearray(line)
        if channels >= 3:  # BGRA -> RGBA (or BGR -> RGB)
            pixel[0::channels], pixel[2::channels] = line[2::channels], line[0::channels]
        if channels == 4:  # undo premultiplication
            for i in range(0, len(pixel), 4):
                alpha = pixel[i + 3]
                if 0 < alpha < 255:
                    for channel in range(3):
                        value = pixel[i + channel] * 255 // alpha
                        pixel[i + channel] = 255 if value > 255 else value
        decoded += b"\x00" + bytes(pixel)  # re-emit with filter type 0

    ihdr = _png_chunk(b"IHDR", header)
    compressed = zlib.compress(bytes(decoded), 9)
    return PNG_SIGNATURE + ihdr + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b"")


def find_icons(path: Path) -> tuple[str, list[tuple[str, int, int, int]]]:
    """Candidate icons in the ipa's main bundle.

    Returns `(app bundle name, [(file name inside the bundle, width, height,
    byte size), ...])`, largest first.
    """
    if not path.is_file():
        raise IconError("no such file")

    app_name, info = find_main_app(path)
    prefix = f"Payload/{app_name}.app/"
    entries = {ICON_SUFFIX.sub("", name).casefold() for name in _icon_entries(info)}

    candidates: list[tuple[str, int, int, int]] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            # Only the bundle root: nested PlugIns/*.appex and Watch/*.app carry
            # their own icons, which are not the app's icon.
            if not name.startswith(prefix) or name.count("/") != 2:
                continue
            file_name = name[len(prefix) :]
            if not file_name.lower().endswith(IMAGE_SUFFIXES):
                continue
            listed = ICON_SUFFIX.sub("", file_name.rsplit(".", 1)[0]).casefold() in entries
            if not listed and not ICON_NAME_HINT.search(file_name):
                continue
            data = archive.read(name)
            if data.startswith(PNG_SIGNATURE):
                width, height = _png_size(data)
            elif data[:2] == b"\xff\xd8":
                width, height = _jpeg_size(data)
            else:
                continue
            candidates.append((file_name, width, height, len(data)))

    if not candidates:
        raise IconError(
            f"no icon file in {app_name}.app — the artwork may live only in "
            "Assets.car (LZFSE, unreadable here); look in the project's repo"
        )
    candidates.sort(key=lambda item: (item[1] * item[2], item[3]), reverse=True)
    return app_name, candidates


def read_icon(path: Path, app_name: str, candidate: tuple[str, int, int, int]) -> bytes:
    """The icon's image bytes, decoded to a standard PNG when it is CgBI."""
    file_name = candidate[0]
    with zipfile.ZipFile(path) as archive:
        data = archive.read(f"Payload/{app_name}.app/{file_name}")
    return decode_cgbi(data) if _is_cgbi(data) else data


def _report_candidates(candidates: list[tuple[str, int, int, int]]) -> None:
    for file_name, width, height, size in candidates:
        print(f"{width}x{height}\t{size:>9} bytes\t{file_name}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract the app icon from an .ipa (largest icon file in the bundle).",
        epilog="Stdout is the written path alone; candidate details go to stderr.",
    )
    parser.add_argument("ipa", type=Path, help="path to an .ipa file")
    parser.add_argument("--out", type=Path, default=Path("icon.png"), help="output file (default: ./icon.png)")
    parser.add_argument("--list", action="store_true", help="list the candidate icons and exit")
    parser.add_argument("--force", action="store_true", help="overwrite the output file if it exists")
    args = parser.parse_args(argv)

    try:
        app_name, candidates = find_icons(args.ipa)
        _report_candidates(candidates)
        if args.list:
            return 0

        out: Path = args.out
        if out.exists() and not args.force:
            print(
                f"error: {out} already exists — pass --force to replace it (the repo "
                "icon may be better than the ipa's, check both)",
                file=sys.stderr,
            )
            return 1

        file_name, width, height, _size = candidates[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(read_icon(args.ipa, app_name, candidates[0]))
        print(f"wrote {out} ({width}x{height}, from {app_name}.app/{file_name})", file=sys.stderr)
        if not file_name.lower().endswith(".png"):
            print(
                f"note: {file_name} is not a PNG — the bytes were copied as-is, so "
                f"{out} keeps that format despite its name",
                file=sys.stderr,
            )
        if width < 512:
            print(
                f"warning: only {width}x{height} — the 1024px artwork is in Assets.car "
                "(unreadable); prefer the project's own icon if it has one",
                file=sys.stderr,
            )
        print(out)
    except IpaError as exc:
        print(f"error: {args.ipa}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
