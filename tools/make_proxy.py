#!/usr/bin/env python3
"""Build all-apps-proxy.json — all-apps.json with its fetch URLs proxied.

GitHub is reachable only intermittently from mainland China, so the assets the
source points at can fail even when the source itself is loaded from a CDN.
This script rewrites the URLs that AltStore/SideStore actually fetches — the
repo's own raw files (icons, screenshots, news images) and release asset
downloads — to go through gh-proxy.com:

  https://raw.githubusercontent.com/...                 ->  https://gh-proxy.com/<same>
  https://github.com/<owner>/<repo>/releases/download/...  ->  https://gh-proxy.com/<same>

Everything else is left untouched on purpose: `website`, `news[].url` and
link text point at GitHub *pages* that users open in a browser, not at files
AltStore downloads, and they read fine as plain GitHub links.

Only strings are touched; every other field is copied verbatim. Running it on
an already-proxied file is a no-op (proxied URLs no longer start with a GitHub
host), so it is safe to re-run.

The result is committed next to all-apps.json by .github/workflows/update.yml;

Stdlib only, so the bare system `python3` runs it.

Usage:
  tools/make_proxy.py                          # all-apps.json -> all-apps-proxy.json
  tools/make_proxy.py in.json out.json
  tools/make_proxy.py --prefix https://gh-proxy.com/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_INPUT = Path("all-apps.json")
DEFAULT_OUTPUT = Path("all-apps-proxy.json")
DEFAULT_PREFIX = "https://gh-proxy.com/"

# The two kinds of URL AltStore/SideStore actually fetches. gh-proxy.com
# accepts the full original URL, so the rewrite is a plain string concatenation.
RAW_HOST_PREFIX = "https://raw.githubusercontent.com/"

# Release asset downloads: /releases/download/<tag>/<file> (and the
# /releases/latest/download/<file> spelling GitHub also serves). Release pages
# (`/releases/tag/...`) are deliberately not matched.
RELEASE_DOWNLOAD = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/releases/(?:latest/)?download/"
)


def is_proxied_url(value: str) -> bool:
    return value.startswith(RAW_HOST_PREFIX) or RELEASE_DOWNLOAD.match(value) is not None


def rewrite(node: object, prefix: str, counter: list[int]) -> object:
    """Return `node` with every raw/release-download URL prefixed by `prefix`."""
    if isinstance(node, str):
        if is_proxied_url(node):
            counter[0] += 1
            return prefix + node
        return node
    if isinstance(node, list):
        return [rewrite(item, prefix, counter) for item in node]
    if isinstance(node, dict):
        return {key: rewrite(value, prefix, counter) for key, value in node.items()}
    return node


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a gh-proxy.com mirror of an AltStore source."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"source to read (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"file to write (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"proxy to prepend to GitHub URLs (default: {DEFAULT_PREFIX})",
    )
    args = parser.parse_args()

    try:
        source = json.loads(args.input.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"Error: cannot read {args.input}: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Error: {args.input} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    counter = [0]
    proxied = rewrite(source, args.prefix, counter)

    args.output.write_text(
        json.dumps(proxied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Rewrote {counter[0]} GitHub URL(s): {args.input} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
