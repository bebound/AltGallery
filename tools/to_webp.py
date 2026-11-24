#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=12.3.0"]
# ///
"""Re-encode an app's artwork as WebP, in place.

Every image in an app folder — the icon and the screenshots, whether they were
downloaded upstream or placed by hand — is stored as WebP, so the repository
and the sources it publishes carry one format. The file keeps its stem and
changes its extension (`home.png` -> `home.webp`); the original is deleted
only after the WebP was written.

Two encodings, picked by the file's stem: a file named `icon` is stored
lossless or at q92, whichever is smaller (flat artwork with sharp edges is
often smaller lossless, and the promo image draws it at a large size);
everything else is lossy q82 — photographic, and this is the size the gallery
actually downloads.

Both qualities are the ones `tools/build_site.py` serves. An embedded ICC
profile (most screenshots are Display P3) is carried into the WebP, so colours
do not shift; resolution is left alone — the icon stays at its full 1024 and
screenshots keep their native size.

Usage (uv reads the inline PEP 723 metadata):
  uv run tools/to_webp.py apps/Foo/icon.png apps/Foo/images/*

A file that is already WebP is skipped, so a rerun is harmless. Do not pass
`images/news.webp` — `render_news.py` owns that file, and it is already WebP.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image

ICON_QUALITY = 92
IMAGE_QUALITY = 82
WEBP_METHOD = 6


def human(size: int) -> str:
    return f"{size / 1024:.0f} KiB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.2f} MiB"


def save(image: Image.Image, profile: bytes | None, **options) -> bytes:
    buffer = io.BytesIO()
    if profile:
        options["icc_profile"] = profile
    image.save(buffer, "WEBP", method=WEBP_METHOD, **options)
    return buffer.getvalue()


def encoded(path: Path) -> bytes:
    """The WebP bytes for ``path``, encoded at the quality its stem calls for."""
    image = Image.open(path)
    image.load()
    profile = image.info.get("icc_profile") or None
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        image = image.convert("RGBA")
    else:
        image = image.convert("RGB")
    if path.stem != "icon":
        return save(image, profile, quality=IMAGE_QUALITY)
    lossless = save(image, profile, lossless=True)
    lossy = save(image, profile, quality=ICON_QUALITY)
    return min(lossless, lossy, key=len)


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-encode artwork as WebP, in place.")
    parser.add_argument("paths", nargs="+", type=Path, help="image files to convert")
    args = parser.parse_args()

    status = 0
    for path in args.paths:
        if not path.is_file():
            print(f"skip  {path}: not a file", file=sys.stderr)
            status = 1
            continue
        if path.suffix.lower() == ".webp":
            print(f"skip  {path}: already WebP", file=sys.stderr)
            continue
        target = path.with_suffix(".webp")
        if target.exists():
            print(f"skip  {path}: {target.name} already exists", file=sys.stderr)
            status = 1
            continue
        try:
            before = path.stat().st_size
            data = encoded(path)
            target.write_bytes(data)
            path.unlink()
        except Exception as exc:  # unreadable image, unwritable directory, ...
            print(f"fail  {path}: {exc}", file=sys.stderr)
            status = 1
            continue
        print(f"{target}  {human(before)} -> {human(len(data))}")
    return status


if __name__ == "__main__":
    sys.exit(main())
