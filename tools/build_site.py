#!/usr/bin/env python3
"""Stage the AltGallery GitHub Pages site in _site/.

The page source is three files — site/index.html, site/style.css and
site/app.js — and the deployed page fetches all-apps.json (same origin) at
runtime. Every image it renders (logos, icons, screenshots) is copied
into _site/media/ beside the page, so the site serves its own artwork
instead of pointing at raw.githubusercontent.com — a CDN in front of the site
(Cloudflare Polish, for one) can then cache and convert it. Only images move:
links the page merely points at (release pages, ipa downloads, AltStore
sources) stay on GitHub. The copies keep the path the file has in the
repository, so the page swaps the raw prefix for media/ (the prefixes are in
config.json) and needs no per-file index.

The build validates the generated sources against their gh-proxy mirror and
stages everything the site needs:

  _site/index.html           page shell; style.css/app.js carry content hashes
  _site/style.css            page styles
  _site/app.js               page script
  _site/media/<repo path>    every displayed image, path unchanged
  _site/all-apps.json        catalog the page fetches (copy of the source)
  _site/all-apps-proxy.json  gh-proxy mirror (kept for download/compare)
  _site/config.json          repo, raw base and proxy prefix derived here
  _site/preview.html         local preview: CSS, JS and the catalog inlined,
                             so it opens from file://; it draws media/ from
                             the same directory

all-apps-proxy.json must match all-apps.json exactly, except that
tools/make_proxy.py rewrites the URLs AltStore fetches. The proxy prefix is
derived from the mirror and written to config.json, so the page's Direct/
Mirror switch and its per-app proxy subscriptions always agree with the
mirror file. Per-app sources are checked for existence (a missing one means
the subscription button would 404).

Display images come out of the working tree: a raw URL of this repository maps
straight back to a repository path and is copied from there. Images hosted
anywhere else are left on their original URL.

The build also shrinks what it copies, since the catalog ships multi-megabyte
PNG artwork that the page never draws at full size:

  * app icons are resized to 128x128 (the largest CSS box is 84px, so this
    still covers a 2x display) and the site's own logo to 256x256;
  * screenshots are capped at SCREENSHOT_MAX_HEIGHT, well above the tallest
    box they render in;
  * every image is re-encoded to WebP and kept only if that is smaller than
    the original bytes, otherwise the original format is served as before.

Because the extension can change, the copies no longer keep the repository
path verbatim in every case: config.json's "mediaFiles" maps a repository
path to the file to serve, and the page resolves a display URL through it.

Local preview (pick either):

  python3 tools/build_site.py && open _site/preview.html   # no server needed
  python3 tools/build_site.py && python3 -m http.server -d _site

Needs Pillow (it is in requirements.txt, so a uv venv has it).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

from PIL import Image

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
MEDIA_DIR = "media"

# Rendering budgets. The page draws an app icon at most at 84 CSS px (hero and
# detail header), so 128 px still covers a 2x display; the site logo is drawn
# at up to 96 px. Screenshots render at most 340 px tall in the strip.
ICON_PX = 128
LOGO_PX = 256
SCREENSHOT_MAX_HEIGHT = 800
WEBP_QUALITY = 82
ICON_WEBP_QUALITY = 92


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


def ref_bases(raw_base: str) -> list[str]:
    """The raw-URL prefixes of this repository's default branch, both forms."""
    owner, repo, tail = raw_base[len(RAW_HOST):].split("/", 2)
    ref = tail.strip("/")
    short = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    return [
        f"{RAW_HOST}{owner}/{repo}/refs/heads/{short}/",
        f"{RAW_HOST}{owner}/{repo}/{short}/",
    ]


def repo_relative(url: str, raw_base: str) -> str | None:
    """The path a raw URL has inside this repository, if it is one of ours."""
    for base in ref_bases(raw_base):
        if url.startswith(base):
            return unquote(url[len(base):].split("?", 1)[0])
    return None


def display_images(source: dict) -> list[str]:
    """Every image URL the page renders: logos, icons and screenshots.

    News artwork is not displayed — the recent-updates rail draws its promo
    tile in markup instead of loading the generated news.png — so those files
    stay out of media/ even though the catalog still links them.
    """
    urls = [source.get("iconURL") or ""]
    for app in source.get("apps", []):
        urls.append(app.get("iconURL") or "")
        urls.extend(app.get("screenshots") or [])
    return sorted({url for url in urls if url})


def open_image(path: Path) -> tuple[Image.Image, bytes | None]:
    """Open an image in a mode WebP can encode, keeping transparency.

    The ICC profile comes back separately: most of these screenshots were
    captured on a Display P3 device, and a WebP without the profile renders
    with shifted colours.
    """
    image = Image.open(path)
    image.load()
    profile = image.info.get("icc_profile") or None
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        return image.convert("RGBA"), profile
    return image.convert("RGB"), profile


def fit_box(image: Image.Image, box: int) -> Image.Image:
    """Downscale into a box x box square, never enlarging."""
    if image.width <= box and image.height <= box:
        return image
    resized = image.copy()
    resized.thumbnail((box, box), Image.Resampling.LANCZOS)
    return resized


def limit_height(image: Image.Image, max_height: int) -> Image.Image:
    """Downscale to max_height tall, never enlarging."""
    if image.height <= max_height:
        return image
    width = max(1, round(image.width * max_height / image.height))
    return image.resize((width, max_height), Image.Resampling.LANCZOS)


def webp_bytes(image: Image.Image, quality: int | None, profile: bytes | None) -> bytes:
    buffer = io.BytesIO()
    options = {"method": 6}
    if profile:
        options["icc_profile"] = profile
    if quality is None:
        image.save(buffer, "WEBP", lossless=True, **options)
    else:
        image.save(buffer, "WEBP", quality=quality, **options)
    return buffer.getvalue()


def optimized_bytes(kind: str, local: Path) -> bytes:
    """The smallest WebP encoding worth serving for this image.

    Icons and the logo are small and flat, so lossless usually beats lossy;
    screenshots are photographic and only worth a lossy encode.
    """
    image, profile = open_image(local)
    if kind == "logo":
        image = fit_box(image, LOGO_PX)
    elif kind == "icon":
        image = fit_box(image, ICON_PX)
    else:
        image = limit_height(image, SCREENSHOT_MAX_HEIGHT)
    candidates = (
        [webp_bytes(image, None, profile), webp_bytes(image, ICON_WEBP_QUALITY, profile)]
        if kind in ("icon", "logo")
        else [webp_bytes(image, WEBP_QUALITY, profile)]
    )
    return min(candidates, key=len)


def image_kind(url: str, icon_urls: set[str], logo_url: str) -> str:
    if url == logo_url:
        return "logo"
    if url in icon_urls:
        return "icon"
    return "screenshot"


def stage_media(source: dict, raw_base: str, out_dir: Path) -> dict[str, str]:
    """Stage every displayed image into <out_dir>/media/.

    Icons and screenshots are downscaled and re-encoded to WebP when that
    makes them smaller; anything else is copied verbatim. Returns the served
    path for each repository path, which config.json hands to the page — the
    two differ when an image became a .webp.
    """
    media_root = out_dir / MEDIA_DIR
    icon_urls = {app.get("iconURL") for app in source.get("apps", [])}
    logo_url = source.get("iconURL") or ""
    served: dict[str, str] = {}
    taken: set[str] = set()
    before = after = copied = 0

    # Start clean: a re-encoded image changes extension, and a stale copy of
    # the old one would otherwise be deployed alongside it.
    if media_root.exists():
        shutil.rmtree(media_root)

    for url in display_images(source):
        relative = repo_relative(url, raw_base)
        if relative is None:
            continue
        local = REPO_ROOT / relative
        if not local.is_file():
            warn(f"{relative}: not in the working tree; the page will miss it under media/")
            continue

        data = local.read_bytes()
        target = relative
        try:
            webp = optimized_bytes(image_kind(url, icon_urls, logo_url), local)
        except Exception as exc:  # unreadable or unsupported artwork
            warn(f"{relative}: cannot re-encode ({exc}); serving it unchanged")
        else:
            webp_path = str(Path(relative).with_suffix(".webp"))
            # Two sources (home.png and home.jpg, say) can want the same name;
            # the first one keeps it and the rest stay in their own format.
            if webp is not None and len(webp) < len(data) and webp_path not in taken:
                data, target = webp, webp_path
        path = media_root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        served[relative] = target
        taken.add(target)
        copied += 1
        before += local.stat().st_size
        after += len(data)

    print(
        f"Staged {copied} display images in {MEDIA_DIR}/: "
        f"{before / 1024 / 1024:.1f} MB -> {after / 1024 / 1024:.1f} MB"
    )
    return served


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
    media_files = stage_media(source, raw_base, out_dir)

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
        "rawBases": ref_bases(raw_base),
        "mediaBase": MEDIA_DIR + "/",
        # Repository path -> file actually staged, e.g.
        # "apps/X/images/home.png": "apps/X/images/home.webp".
        "mediaFiles": media_files,
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
