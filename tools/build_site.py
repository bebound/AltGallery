#!/usr/bin/env python3
"""Stage the AltGallery GitHub Pages site in _site/.

The page source is three files — site/index.html, site/style.css and
site/app.js — and the deployed page fetches all-apps.json (same origin) at
runtime, loading icons, screenshots and news images from the URLs in that
file. The build validates the generated sources against their gh-proxy mirror
and stages everything the site needs:

  _site/index.html           page shell; style.css/app.js carry content hashes
  _site/style.css            page styles
  _site/app.js               page script
  _site/all-apps.json        catalog the page fetches (copy of the source)
  _site/all-apps-proxy.json  gh-proxy mirror (kept for download/compare)
  _site/config.json          repo, raw base and proxy prefix derived here
  _site/preview.html         local preview: CSS, JS and the catalog inlined,
                             so it opens from file:// without a web server

all-apps-proxy.json must match all-apps.json exactly, except that
tools/make_proxy.py rewrites the URLs AltStore fetches. The proxy prefix is
derived from the mirror and written to config.json, so the page's Direct/
Mirror switch and its per-app proxy subscriptions always agree with the
mirror file. Per-app sources are checked for existence (a missing one means
the subscription button would 404).

Local preview (pick either):

  python3 tools/build_site.py && open _site/preview.html   # single file, no server
  python3 tools/build_site.py && python3 -m http.server -d _site

Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path("all-apps.json")
DEFAULT_PROXY = Path("all-apps-proxy.json")
DEFAULT_SITE = Path("site")
DEFAULT_OUT_DIR = Path("_site")

RAW_HOST = "https://raw.githubusercontent.com/"
RELEASE_DOWNLOAD = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/releases/(?:latest/)?download/"
)
APP_FOLDER = re.compile(r"/apps/([^/]+)/")
RAW_BASE = re.compile(
    r"^(https://raw\.githubusercontent\.com/[^/]+/[^/]+/(?:refs/heads/[^/]+|master)/)"
)
DEFAULT_PROXY_PREFIX = "https://gh-proxy.com/"


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"error: cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {path} is not valid JSON: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("apps"), list):
        raise SystemExit(f"error: {path} does not look like an AltStore source")
    return data


def is_proxied_url(value: str) -> bool:
    return value.startswith(RAW_HOST) or RELEASE_DOWNLOAD.match(value) is not None


def walk_pairs(direct: object, proxied: object, path: str = "$"):
    """Yield (path, direct value, proxy value) for every string in both trees."""
    if isinstance(direct, str) and isinstance(proxied, str):
        yield path, direct, proxied
    elif isinstance(direct, dict) and isinstance(proxied, dict):
        if set(direct) != set(proxied):
            raise SystemExit(
                f"error: all-apps-proxy.json does not match all-apps.json at {path}; "
                "regenerate it with tools/make_proxy.py"
            )
        for key in direct:
            yield from walk_pairs(direct[key], proxied[key], f"{path}.{key}")
    elif isinstance(direct, list) and isinstance(proxied, list):
        if len(direct) != len(proxied):
            raise SystemExit(
                f"error: all-apps-proxy.json does not match all-apps.json at {path}; "
                "regenerate it with tools/make_proxy.py"
            )
        for index, (a, b) in enumerate(zip(direct, proxied)):
            yield from walk_pairs(a, b, f"{path}[{index}]")
    elif direct != proxied:
        raise SystemExit(
            f"error: all-apps-proxy.json does not match all-apps.json at {path}; "
            "regenerate it with tools/make_proxy.py"
        )


def detect_proxy_prefix(source: dict, proxy: dict) -> str:
    """Derive the gh-proxy prefix from the mirror and verify every rewrite."""
    prefixes: set[str] = set()
    for path, direct, proxied in walk_pairs(source, proxy):
        if direct == proxied:
            continue
        if not is_proxied_url(direct):
            raise SystemExit(
                f"error: {path} differs between the source and its mirror even though "
                "make_proxy.py would leave it alone"
            )
        if not proxied.endswith(direct):
            raise SystemExit(f"error: {path}: unexpected mirrored URL {proxied!r}")
        prefixes.add(proxied[: len(proxied) - len(direct)])
    if not prefixes:
        warn("all-apps-proxy.json rewrote no URLs; using the default gh-proxy prefix")
        return DEFAULT_PROXY_PREFIX
    if len(prefixes) > 1:
        raise SystemExit(f"error: multiple proxy prefixes found: {sorted(prefixes)}")
    prefix = prefixes.pop()
    if not prefix.startswith("https://") or not prefix.endswith("/"):
        raise SystemExit(f"error: unexpected proxy prefix {prefix!r}")
    return prefix


def derive_raw_base(source: dict) -> str:
    match = RAW_BASE.match(source.get("iconURL") or "")
    if not match:
        raise SystemExit("error: cannot derive the raw GitHub base from [source] iconURL")
    return match.group(1)


def github_repo_from_raw(raw_base: str) -> str:
    match = re.match(r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", raw_base)
    if not match:
        raise SystemExit(f"error: cannot derive the repository from {raw_base!r}")
    return f"https://github.com/{match.group(1)}/{match.group(2)}"


def check_app_sources(source: dict) -> None:
    for app in source.get("apps", []):
        match = APP_FOLDER.search(app.get("iconURL") or "")
        if not match:
            warn(f"{app.get('name')}: cannot derive its apps/<App> folder from iconURL")
            continue
        folder = unquote(match.group(1))
        for name in ("apps.json", "apps-proxy.json"):
            path = REPO_ROOT / "apps" / folder / name
            if not path.is_file():
                warn(f"{folder}: {path.relative_to(REPO_ROOT)} is missing; subscription links may 404")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def json_blob(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Keep the payload from closing the <script> element it lives in.
    return (
        blob.replace("<", "\\u003c")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def build_preview(index_html: str, style: bytes, script: bytes, source: dict,
                  config: dict, style_tag: str, script_tag: str) -> str:
    """Inline CSS, JS and the catalog so the preview opens from file://."""
    if style_tag not in index_html or script_tag not in index_html:
        raise SystemExit("error: cannot find the style/script tags to inline")
    css = "<style>\n" + style.decode("utf-8").rstrip() + "\n</style>"
    data_script = (
        "<script>window.__ALTGALLERY_DATA__ = "
        + json_blob({"source": source, "config": config})
        + ";</script>"
    )
    js = "<script>\n" + script.decode("utf-8").rstrip() + "\n</script>"
    return index_html.replace(style_tag, css).replace(script_tag, data_script + "\n" + js)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage the AltGallery GitHub Pages site.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--proxy", type=Path, default=DEFAULT_PROXY)
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else REPO_ROOT / path

    source_path = resolve(args.source)
    proxy_path = resolve(args.proxy)
    site_dir = resolve(args.site)
    out_dir = resolve(args.out_dir)

    source = load_json(source_path)
    proxy = load_json(proxy_path)
    if not source.get("apps"):
        raise SystemExit("error: all-apps.json contains no apps")

    raw_base = derive_raw_base(source)
    proxy_prefix = detect_proxy_prefix(source, proxy)
    repo = github_repo_from_raw(raw_base)
    check_app_sources(source)

    for name in ("index.html", "style.css", "app.js"):
        if not (site_dir / name).is_file():
            raise SystemExit(f"error: missing {site_dir / name}")

    out_dir.mkdir(parents=True, exist_ok=True)

    style = (site_dir / "style.css").read_bytes()
    script = (site_dir / "app.js").read_bytes()
    html = (site_dir / "index.html").read_text(encoding="utf-8")

    if 'href="style.css"' not in html or 'src="app.js"' not in html:
        raise SystemExit("error: site/index.html must reference style.css and app.js")

    style_tag = f'<link rel="stylesheet" href="style.css?v={content_hash(style)}">'
    script_tag = f'<script src="app.js?v={content_hash(script)}" defer></script>'
    html = html.replace('href="style.css"', f'href="style.css?v={content_hash(style)}"')
    html = html.replace('src="app.js"', f'src="app.js?v={content_hash(script)}"')

    config = {
        "repo": repo,
        "rawBase": raw_base,
        "proxyPrefix": proxy_prefix,
        "allSource": raw_base + "all-apps.json",
        "allSourceProxy": raw_base + "all-apps-proxy.json",
    }

    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "style.css").write_bytes(style)
    (out_dir / "app.js").write_bytes(script)
    shutil.copyfile(source_path, out_dir / "all-apps.json")
    shutil.copyfile(proxy_path, out_dir / "all-apps-proxy.json")
    (out_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    preview = build_preview(html, style, script, source, config, style_tag, script_tag)
    (out_dir / "preview.html").write_text(preview, encoding="utf-8")

    def display(path: Path) -> str:
        try:
            return str(path.relative_to(REPO_ROOT))
        except ValueError:
            return str(path)

    print(
        f"Built {len(source['apps'])} apps and {len(source.get('news', []))} news entries "
        f"(proxy: {proxy_prefix})"
    )
    for name in (
        "index.html",
        "style.css",
        "app.js",
        "all-apps.json",
        "all-apps-proxy.json",
        "config.json",
        "preview.html",
    ):
        path = out_dir / name
        print(f"  {display(path)}  {path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
