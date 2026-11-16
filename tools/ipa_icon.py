#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["lzfse"]
# ///
"""Extract the app icon from an .ipa (iOS app archive).

Use this when the app has no icon in the repo and nothing usable in the
project's README/assets — it guarantees the *real* shipping artwork, at the
identifier the app actually ships with (see tools/ipa_bundle_id.py for that).

Candidates come from two places:

* the bundle's **loose image files**, named by the app's Info.plist icon keys
  (`CFBundleIcons` → `CFBundlePrimaryIcon` → `CFBundleIconFiles`, the `~ipad`
  variant and the legacy `CFBundleIconFiles`) — `<Entry>@2x.png`,
  `<Entry>@3x.png`, `<Entry>~ipad.png`, … — plus any `*icon*.png` as a safety
  net;
* the app's **`Assets.car`**, the compiled asset catalog. Modern ipas keep only
  120x120 / 152x152 loose icons while the 1024x1024 ("marketing") artwork sits
  in here as LZFSE (`bvx2`)-compressed raw pixels, so this is usually where the
  sharp icon comes from. The catalogue is a BOMStore: a block table points at
  each rendition, whose header names it (`Icon-App-1024x1024@1x.png`), gives
  its pixel size and format (`BGRA`), and is followed by `KCBC` chunks — each a
  little-endian frame header around one LZFSE stream.

  Decoding LZFSE uses the [`lzfse`](https://pypi.org/project/lzfse/) package,
  which wraps Apple's reference implementation and builds everywhere, so the
  catalog is readable on any platform. It is the script's only dependency and
  is declared in the inline metadata below, so `uv run` installs it — which is
  how the tools in this repo are always run.

**The largest candidate wins** (by pixels, then file size). The winner is
written as a flat square PNG — store icons are flat square artwork;
tools/render_news.py applies the rounded mask when it draws.

Apple ships many icons as **CgBI** PNGs (iPhone-optimized: BGRA channel order,
premultiplied alpha, raw-deflate IDAT). Pillow cannot read them ("broken data
stream"); this script decodes them in pure Python and writes a standard PNG, so
the result is directly usable by Pillow (render_news.py) — no `sips` needed.
Standard PNGs and JPEGs are copied byte-for-byte.

Usage (uv reads the inline PEP 723 metadata):
  uv run tools/ipa_icon.py App.ipa                          # -> ./icon.png
  uv run tools/ipa_icon.py App.ipa --out apps/Foo/icon.png   # where the gallery keeps it
  uv run tools/ipa_icon.py App.ipa --list                    # just list the candidates
  uv run tools/ipa_icon.py App.ipa --out icon.png --force    # overwrite an existing file

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
from dataclasses import dataclass
from pathlib import Path

import lzfse

from ipa_bundle_id import IpaError, find_main_app

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Icon entries in Info.plist carry no scale/dimension suffix ("AppIcon60x60");
# the files on disk do ("AppIcon60x60@2x.png", "AppIcon76x76@2x~ipad.png").
ICON_SUFFIX = re.compile(r"[@~-].*$")
ICON_NAME_HINT = re.compile(r"icon", re.IGNORECASE)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")

# Assets.car: rendition header magic, the chunk tags that carry pixel data, and
# the pixel formats whose channel order this script knows how to re-order.
CAR_RENDITION_MAGIC = b"ISTC"
CAR_STREAM_MAGIC = b"bvx2"
CAR_FRAME_MAGIC = b"KCBC"
CAR_CHANNELS = {b"BGRA": 4, b"RGBA": 4, b"ARGB": 4, b"ABGR": 4}


class IconError(IpaError):
    """An ipa whose app icon cannot be extracted."""


@dataclass(frozen=True)
class Candidate:
    """One icon candidate: a loose bundle file, or a rendition in Assets.car."""

    name: str  # file name inside the bundle, or the catalog's rendition name
    width: int
    height: int
    size: int  # bytes it occupies in the ipa
    source: str  # "file" or "car"
    offset: int = 0  # block offset of the rendition inside Assets.car

    @property
    def label(self) -> str:
        return f"{self.name} [Assets.car]" if self.source == "car" else self.name

    @property
    def rank(self) -> tuple[bool, int, int]:
        """Largest first; a rendition named like an icon outranks other artwork."""
        hinted = bool(ICON_NAME_HINT.search(self.name))
        return (hinted, self.width * self.height, self.size)


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


def _lzfse_decompress(data: bytes, limit: int) -> bytes:
    """Decode one LZFSE stream, whose output can be at most `limit` bytes."""
    try:
        out = lzfse.decompress(data)
    except lzfse.error as exc:
        raise IconError(f"cannot decompress an LZFSE rendition: {exc}") from exc
    if len(out) > limit:
        raise IconError(f"rendition decoded to {len(out)} bytes, past the {limit} expected")
    return out


def _car_renditions(car: bytes):
    """Every rendition in an Assets.car: (name, width, height, format, offset, size).

    The file is a BOMStore: an 8-byte `BOMStore` magic, then the version, the
    block count and three offsets (blocks, index, vars — all big-endian). The
    block table holds one (offset, length) pair per block, and an image block
    starts with a rendition header naming it.
    """
    if len(car) < 28 or car[:8] != b"BOMStore":
        raise IconError("not a BOMStore asset catalog")
    _version, block_count, table_offset = struct.unpack(">III", car[8:20])
    if table_offset + 4 + block_count * 8 > len(car):
        raise IconError("truncated asset catalog")
    for index in range(block_count):
        entry = table_offset + 4 + index * 8
        offset, length = struct.unpack(">II", car[entry : entry + 8])
        if not length or offset + length > len(car):
            continue
        block = car[offset : offset + length]
        if block[:4] != CAR_RENDITION_MAGIC or len(block) < 48:
            continue
        width, height = struct.unpack("<II", block[12:20])
        image_format = block[24:28]
        name = block[40:].split(b"\x00", 1)[0].decode("utf-8", "replace")
        yield name, width, height, image_format, offset, length


def _car_pixels(block: bytes, width: int, height: int, image_format: bytes) -> bytes:
    """The rendition's raw pixels, decompressing its LZFSE chunks in order.

    After the header comes either a bare `bvx2` stream or a run of `KCBC`
    frames — a 20-byte frame header (rows and payload length, little-endian)
    around one stream each. A stream decodes to whole rows, so the frames are
    concatenated until the image is complete.
    """
    channels = CAR_CHANNELS.get(image_format)
    if channels is None:
        raise IconError(f"unsupported rendition format {image_format!r}")
    expected = width * height * channels
    start = len(block)
    for magic in (CAR_STREAM_MAGIC, CAR_FRAME_MAGIC):
        found = block.find(magic, 40)
        if 0 <= found < start:
            start = found
    if start >= len(block):
        raise IconError("rendition carries no pixel data")

    pixels = bytearray()
    position = start
    while len(pixels) < expected:
        magic = block[position : position + 4]
        if magic == CAR_FRAME_MAGIC:
            _rows, length = struct.unpack("<II", block[position + 12 : position + 20])
            if position + 20 + length > len(block):
                break
            body = block[position + 20 : position + 20 + length]
            pixels += _lzfse_decompress(body, expected - len(pixels))
            position += 20 + length
        elif magic == CAR_STREAM_MAGIC:
            # A bare stream: the decoder stops at the stream's own end marker,
            # and the next frame (if there is one) is the following KCBC chunk.
            pixels += _lzfse_decompress(block[position:], expected - len(pixels))
            following = block.find(CAR_FRAME_MAGIC, position)
            if following < 0:
                break
            position = following
        else:
            break
    if len(pixels) != expected:
        raise IconError(f"rendition decoded to {len(pixels)} bytes, expected {expected}")
    return bytes(pixels)


def _encode_png(width: int, height: int, pixels: bytes, image_format: bytes) -> bytes:
    """Wrap raw rendition pixels into a standard PNG any decoder can read."""
    alpha = pixels[3::4]
    if image_format == b"BGRA":
        red, green, blue = pixels[2::4], pixels[1::4], pixels[0::4]
    elif image_format == b"ARGB":
        red, green, blue, alpha = pixels[1::4], pixels[2::4], pixels[3::4], pixels[0::4]
    elif image_format == b"ABGR":
        red, green, blue, alpha = pixels[3::4], pixels[2::4], pixels[1::4], pixels[0::4]
    else:  # RGBA
        red, green, blue = pixels[0::4], pixels[1::4], pixels[2::4]
    rgba = bytearray(len(pixels))
    rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = red, green, blue, alpha

    stride = width * 4
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type 0 (None)
        raw += rgba[row * stride : (row + 1) * stride]
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )


def _car_candidates(car: bytes) -> list[Candidate]:
    """The catalog's square, data-bearing image renditions, as icon candidates.

    Only square renditions are considered (a catalog also holds launch images
    and other artwork that would win on pixel count alone), and only those that
    actually carry pixels: actool leaves a short placeholder behind for every
    icon size that the bundle ships as a loose file instead.
    """
    candidates: list[Candidate] = []
    for name, width, height, image_format, offset, length in _car_renditions(car):
        if not width or width != height or image_format not in CAR_CHANNELS:
            continue
        block = car[offset : offset + length]
        if CAR_STREAM_MAGIC not in block and CAR_FRAME_MAGIC not in block:
            continue
        candidates.append(
            Candidate(name or "unnamed rendition", width, height, length, "car", offset)
        )
    return candidates


def find_icons(path: Path) -> tuple[str, list[Candidate]]:
    """Candidate icons in the ipa's main bundle, largest first."""
    if not path.is_file():
        raise IconError("no such file")

    app_name, info = find_main_app(path)
    prefix = f"Payload/{app_name}.app/"
    entries = {ICON_SUFFIX.sub("", name).casefold() for name in _icon_entries(info)}

    candidates: list[Candidate] = []
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
            candidates.append(Candidate(file_name, width, height, len(data), "file"))

        car_name = f"{prefix}Assets.car"
        if car_name in archive.namelist():
            try:
                candidates += _car_candidates(archive.read(car_name))
            except IconError as exc:
                print(f"note: Assets.car skipped — {exc}", file=sys.stderr)

    if not candidates:
        raise IconError(
            f"no icon in {app_name}.app — no listed icon file and no usable "
            "rendition in Assets.car; look in the project's repo"
        )
    candidates.sort(key=lambda item: item.rank, reverse=True)
    return app_name, candidates


def read_icon(path: Path, app_name: str, candidate: Candidate) -> bytes:
    """The icon's image bytes, as a standard PNG."""
    if candidate.source == "car":
        with zipfile.ZipFile(path) as archive:
            car = archive.read(f"Payload/{app_name}.app/Assets.car")
        block = car[candidate.offset : candidate.offset + candidate.size]
        pixels = _car_pixels(block, candidate.width, candidate.height, block[24:28])
        return _encode_png(candidate.width, candidate.height, pixels, block[24:28])

    with zipfile.ZipFile(path) as archive:
        data = archive.read(f"Payload/{app_name}.app/{candidate.name}")
    return decode_cgbi(data) if _is_cgbi(data) else data


def _report_candidates(candidates: list[Candidate]) -> None:
    for candidate in candidates:
        print(
            f"{candidate.width}x{candidate.height}\t{candidate.size:>9} bytes\t{candidate.label}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract the app icon from an .ipa (largest icon, bundle file or Assets.car).",
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

        best = candidates[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(read_icon(args.ipa, app_name, best))
        origin = (
            f"{app_name}.app/Assets.car: {best.name}"
            if best.source == "car"
            else f"{app_name}.app/{best.name}"
        )
        print(f"wrote {out} ({best.width}x{best.height}, from {origin})", file=sys.stderr)
        if best.source == "file" and not best.name.lower().endswith(".png"):
            print(
                f"note: {best.name} is not a PNG — the bytes were copied as-is, so "
                f"{out} keeps that format despite its name",
                file=sys.stderr,
            )
        if best.width < 512:
            print(
                f"warning: only {best.width}x{best.height} — no larger artwork in the "
                "bundle or Assets.car; prefer the project's own icon if it has one",
                file=sys.stderr,
            )
        print(out)
    except IpaError as exc:
        print(f"error: {args.ipa}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
