#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=12.3.0"]
# ///
"""Stage the AltGallery GitHub Pages site in _site/.

The page source is three files — site/index.html, site/style.css and
site/app.js — plus the site/i18n/ overlays that carry the page's non-English
app text. The deployed page fetches all-apps.json (same origin) at runtime.
Every image it renders (logos, icons, screenshots) is copied
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
  _site/vendor/              vendored Embla builds the rail loads, plus the
                             MIT notice; hashed like app.js
  _site/favicon.ico          the site icons, all drawn from the source logo:
  _site/favicon-*.png        the tab set (16/32/48 frames in the .ico, plus
  _site/apple-touch-icon.png 16/32/96 PNGs), the 180 px touch icon iOS puts on
  _site/web-app-manifest-*   the home screen, the 192/512 icons Chrome/Android
  _site/maskable-512x512.png and Edge install from, and the opaque maskable
                             copy Android cuts its launcher shape out of
  _site/site.webmanifest     app name, colors and those icons
  _site/media/<repo path>    every displayed image, path unchanged
  _site/all-apps.json        catalog the page fetches (copy of the source)
  _site/all-apps-proxy.json  gh-proxy mirror (kept for download/compare)
  _site/config.json          repo, raw base and proxy prefix derived here,
                             plus the site/i18n/ text overlays
  _site/preview.html         local preview: CSS, JS and the catalog inlined,
                             so it opens from file://; it draws media/ from
                             the same directory

The page also loads a page-view analytics script from its own host, inline in
site/index.html; it is the one external script the deployed page needs.

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

The site's own icons are rendered from the source logo (the same artwork the
page shows in its header). They are static files linked from the HTML and the
manifest rather than an img the page sets from JavaScript, because a browser
captures a favorite's or a home-screen shortcut's icon when it is added, before
the catalog has loaded.

Every icon is that one drawing at the size its surface asks for, so no client
has to downscale a large file into a blurry tab: 16/32/48 frames in
favicon.ico, the same three as PNGs beside it plus a 96 px one (Google Search
only draws a favicon whose size is a multiple of 48), the 180 px touch icon for
the iOS home screen, and 192/512 px for the Web App Manifest that
Chrome/Android and Edge install from. favicon.ico is also the file the clients
that never read the page — feed readers, bookmark managers, link previews,
crawlers — request by name, and a 404 there is what leaves the site unbranded
in those lists.

The tab icons keep the logo's transparent rounded corners, so a browser draws
the artwork as it was made on whatever tab strip it has. The touch icon and the
maskable copy are composited onto the catalog's tint instead: iOS paints an
alpha channel black on the home screen, and a maskable icon has to be opaque,
or Android's launcher mask would leave its corners empty.

Because the extension can change, the copies no longer keep the repository
path verbatim in every case: config.json's "mediaFiles" maps a repository
path to the file to serve, and the page resolves a display URL through it.

Local preview (pick either, from the repo root; uv reads the inline PEP 723
metadata and installs Pillow):

  uv run tools/build_site.py && open _site/preview.html   # no server needed
  uv run tools/build_site.py && python3 -m http.server -d _site
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

from PIL import Image, ImageOps

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

# Third-party scripts the page loads from site/vendor/ and the build copies
# beside it, in load order. Vendored rather than pulled from a CDN: the site
# serves its own assets so it keeps working where a CDN is blocked, and so
# preview.html still runs from file://.
VENDOR_DIR = "vendor"
VENDOR_SCRIPTS = (
    "embla-carousel.umd.js",  # EmblaCarousel
    "embla-carousel-auto-scroll.umd.js",  # EmblaCarouselAutoScroll
)
# Staged next to them: MIT requires the notice to travel with the code.
VENDOR_FILES = VENDOR_SCRIPTS + ("embla.LICENSE.txt",)

# Rendering budgets. The page draws an app icon at most at 84 CSS px (hero and
# detail header), so 128 px still covers a 2x display; the site logo is drawn
# at up to 96 px. Screenshots render at most 340 px tall in the strip.
ICON_PX = 128
LOGO_PX = 256
SCREENSHOT_MAX_HEIGHT = 800
WEBP_QUALITY = 82
ICON_WEBP_QUALITY = 92

# The site's own icons, all resampled from one square master fitted to the
# source logo. Each surface gets a file of the size it draws (see
# write_site_icons), so none of them has to downscale a big one.
SITE_ICON_PX = 256

# The tab. favicon.ico carries these frames for the clients that read the file
# itself, and the PNGs are what <link rel="icon"> points at. 96 px is in the
# list because Google Search only draws a favicon whose size is a multiple of
# 48 (48, 96, 144…), and 96 is the smallest that still looks sharp on a 2x tab.
SITE_FAVICON_SIZES = ((16, 16), (32, 32), (48, 48))
SITE_FAVICON_PNGS = (16, 32, 96)

# The iOS home-screen web clip, the size Apple asks for.
APPLE_TOUCH_ICON_PX = 180

# The Web App Manifest icons Chrome/Android and Edge install from. 192 and 512
# are the two sizes such an install uses; the maskable copy is the same drawing
# grown onto an opaque square, because Android cuts the launcher's shape out of
# a maskable icon and would otherwise leave its transparent corners empty.
MANIFEST_ICON_SIZES = (192, 512)
MASKABLE_ICON_PX = 512

# The colour the touch icon and the maskable one are flattened onto when the
# catalog carries no tint of its own.
DEFAULT_TINT = "#3B82F6"


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"error: cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise SystemExit(f"error: {path} must contain a JSON object")
    return data


def load_json(path: Path) -> dict:
    data = read_json(path)
    if not isinstance(data.get("apps"), list):
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
                "regenerate it with `uv run tools/make_proxy.py`"
            )
        for key in direct:
            yield from walk_pairs(direct[key], proxied[key], f"{path}.{key}")
    elif isinstance(direct, list) and isinstance(proxied, list):
        if len(direct) != len(proxied):
            raise SystemExit(
                f"error: all-apps-proxy.json does not match all-apps.json at {path}; "
                "regenerate it with `uv run tools/make_proxy.py`"
            )
        for index, (a, b) in enumerate(zip(direct, proxied)):
            yield from walk_pairs(a, b, f"{path}[{index}]")
    elif direct != proxied:
        raise SystemExit(
            f"error: all-apps-proxy.json does not match all-apps.json at {path}; "
            "regenerate it with `uv run tools/make_proxy.py`"
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
    tile in markup instead of loading the generated news.webp — so those files
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


def tint_color(source: dict) -> str:
    """The catalog's brand colour, checked so Pillow can fill with it."""
    tint = source.get("tintColor") or DEFAULT_TINT
    try:
        Image.new("RGB", (1, 1), tint)
    except ValueError:
        warn(f"unreadable tintColor {tint!r}; using {DEFAULT_TINT}")
        return DEFAULT_TINT
    return tint


def write_site_icons(logo_path: Path, out_dir: Path, tint: str) -> list[str]:
    """Write the site's icon files, one per surface that draws one.

    The source logo is fitted to one square master, and every file below is a
    resampling of that master, so a tab, an iOS home screen and an Android
    launcher each get exactly the size they ask for. Returns the file names
    written, which the build report lists.

    The tab icons keep the logo's transparent rounded corners; the touch icon
    and the maskable copy are flattened onto the tint, since iOS draws alpha as
    black on the home screen and a maskable icon must have no transparent
    pixels at all — Android cuts the launcher's shape out of it.
    """
    logo = Image.open(logo_path)
    logo.load()
    # A crop to the square, not a stretch: the logo is not guaranteed to be one.
    artwork = ImageOps.fit(
        logo.convert("RGBA"), (SITE_ICON_PX, SITE_ICON_PX), Image.Resampling.LANCZOS
    )

    def scaled(size: int) -> Image.Image:
        return artwork.resize((size, size), Image.Resampling.LANCZOS)

    def opaque(size: int) -> Image.Image:
        canvas = Image.new("RGBA", (size, size), tint)
        canvas.alpha_composite(scaled(size))
        return canvas.convert("RGB")

    written = []
    for size in SITE_FAVICON_PNGS:
        name = f"favicon-{size}x{size}.png"
        scaled(size).save(out_dir / name, optimize=True)
        written.append(name)

    # PNG-compressed frames: the same three sizes as uncompressed BMP frames
    # would take several times the bytes for no gain at these sizes.
    artwork.save(
        out_dir / "favicon.ico",
        format="ICO",
        sizes=SITE_FAVICON_SIZES,
        bitmap_format="png",
    )
    written.append("favicon.ico")

    opaque(APPLE_TOUCH_ICON_PX).save(out_dir / "apple-touch-icon.png", optimize=True)
    written.append("apple-touch-icon.png")

    for size in MANIFEST_ICON_SIZES:
        name = f"web-app-manifest-{size}x{size}.png"
        scaled(size).save(out_dir / name, optimize=True)
        written.append(name)

    maskable = f"maskable-{MASKABLE_ICON_PX}x{MASKABLE_ICON_PX}.png"
    opaque(MASKABLE_ICON_PX).save(out_dir / maskable, optimize=True)
    written.append(maskable)
    return written


def manifest_icons() -> list[dict]:
    icons = [
        {
            "src": f"web-app-manifest-{size}x{size}.png",
            "sizes": f"{size}x{size}",
            "type": "image/png",
            "purpose": "any",
        }
        for size in MANIFEST_ICON_SIZES
    ]
    icons.append(
        {
            "src": f"maskable-{MASKABLE_ICON_PX}x{MASKABLE_ICON_PX}.png",
            "sizes": f"{MASKABLE_ICON_PX}x{MASKABLE_ICON_PX}",
            "type": "image/png",
            "purpose": "maskable",
        }
    )
    return icons


def write_manifest(source: dict, out_dir: Path) -> None:
    """Write _site/site.webmanifest.

    This is what Chrome/Android and Edge read when the page is installed to the
    home screen or app launcher; iOS takes its touch icon from the HTML and
    only reads the name and the launch background from here.

    The file keeps the conventional .webmanifest extension: GitHub Pages, the
    host the page is published from, serves it as application/manifest+json —
    the type a browser expects for a manifest — and so does any host that reads
    content types from the standard mime table.

    An icon marked "any" is drawn as it was made; the "maskable" one is the
    same drawing on the tint, which is what Android fills its launcher shape
    with.
    """
    name = source.get("name") or "AltGallery"
    tint = tint_color(source)
    manifest = {
        "name": name,
        "short_name": name,
        "description": source.get("subtitle") or "",
        "start_url": ".",
        "scope": ".",
        "display": "standalone",
        "background_color": tint,
        "theme_color": tint,
        "icons": manifest_icons(),
    }
    (out_dir / "site.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


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

        original = local.read_bytes()
        data = original
        target = relative
        try:
            webp = optimized_bytes(image_kind(url, icon_urls, logo_url), local)
        except Exception as exc:  # unreadable or unsupported artwork
            warn(f"{relative}: cannot re-encode ({exc}); serving it unchanged")
        else:
            webp_path = str(Path(relative).with_suffix(".webp"))
            # Two sources (home.png and home.jpg, say) can want the same name;
            # the first one keeps it and the rest stay in their own format.
            if len(webp) < len(original) and webp_path not in taken:
                data, target = webp, webp_path
        path = media_root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        served[relative] = target
        taken.add(target)
        copied += 1
        before += len(original)
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


def load_i18n(site_dir: Path, source: dict) -> dict[str, dict[str, dict[str, str]]]:
    """Read site/i18n/<lang>.json — hand-maintained text overlays for the page.

    An AltStore source carries exactly one language per app (localizedDescription
    is a plain string, with no per-locale variants), so the Chinese subtitles and
    descriptions cannot live in all-apps.json without taking the Chinese text
    away from English readers. They live here instead, keyed by bundle
    identifier, and the build folds them into config.json, which the page's
    language switch reads. An app with no entry keeps its catalog text, which is
    already Chinese for the Chinese-only projects.

    A key beginning with "_" is a comment, not an app.
    """
    i18n_dir = site_dir / "i18n"
    if not i18n_dir.is_dir():
        return {}
    known = {app.get("bundleIdentifier") for app in source.get("apps", [])}
    overlay: dict[str, dict[str, dict[str, str]]] = {}
    for path in sorted(i18n_dir.glob("*.json")):
        table: dict[str, dict[str, str]] = {}
        for bundle_id, entry in read_json(path).items():
            if bundle_id.startswith("_"):
                continue
            where = f"{path.relative_to(REPO_ROOT)}: {bundle_id}"
            if bundle_id not in known:
                warn(f"{where} is not in the catalog; remove the entry or fix the bundle identifier")
                continue
            if not isinstance(entry, dict):
                warn(f"{where} must map to an object with subtitle/description")
                continue
            fields = {}
            for key, value in entry.items():
                if key not in ("subtitle", "description"):
                    warn(f"{where} has an unknown field {key!r}")
                elif isinstance(value, str) and value.strip():
                    fields[key] = value
            if fields:
                table[bundle_id] = fields
        overlay[path.stem] = table
    return overlay


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def json_blob(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Keep the payload from closing the <script> element it lives in, and spell
    # the two JavaScript line terminators as escapes: JSON allows them raw, but
    # they are invisible in this source and inside a string literal.
    return (
        blob.replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def inline_script(data: bytes) -> str:
    text = data.decode("utf-8").rstrip()
    # Inlining is a textual splice, so a script that closes its own element
    # would end the <script> it is spliced into.
    if "</script" in text.lower():
        raise SystemExit("error: cannot inline a script containing </script>")
    return "<script>\n" + text + "\n</script>"


def build_preview(index_html: str, style: bytes, script: bytes, vendor: dict[str, bytes],
                  vendor_tags: dict[str, str], source: dict, config: dict,
                  style_tag: str, script_tag: str) -> str:
    """Inline CSS, JS and the catalog so the preview opens from file://."""
    if style_tag not in index_html or script_tag not in index_html:
        raise SystemExit("error: cannot find the style/script tags to inline")
    # The vendored scripts are inlined where they load, ahead of app.js.
    for tag, name in vendor_tags.items():
        if tag not in index_html:
            raise SystemExit(f"error: cannot find the script tag for {VENDOR_DIR}/{name}")
        index_html = index_html.replace(tag, inline_script(vendor[name]))
    css = "<style>\n" + style.decode("utf-8").rstrip() + "\n</style>"
    data_script = (
        "<script>window.__ALTGALLERY_DATA__ = "
        + json_blob({"source": source, "config": config})
        + ";</script>"
    )
    js = inline_script(script)
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
    vendor = {}
    for name in VENDOR_FILES:
        path = site_dir / VENDOR_DIR / name
        if not path.is_file():
            raise SystemExit(f"error: missing {path}")
        vendor[name] = path.read_bytes()

    out_dir.mkdir(parents=True, exist_ok=True)
    media_files = stage_media(source, raw_base, out_dir)

    logo_relative = repo_relative(source.get("iconURL") or "", raw_base)
    icon_names: list[str] = []
    if logo_relative and (REPO_ROOT / logo_relative).is_file():
        icon_names = write_site_icons(
            REPO_ROOT / logo_relative, out_dir, tint_color(source)
        )
    else:
        warn("cannot find the site logo in the working tree; the page will have no icon")
    write_manifest(source, out_dir)
    i18n = load_i18n(site_dir, source)

    style = (site_dir / "style.css").read_bytes()
    script = (site_dir / "app.js").read_bytes()
    html = (site_dir / "index.html").read_text(encoding="utf-8")

    if 'href="style.css"' not in html or 'src="app.js"' not in html:
        raise SystemExit("error: site/index.html must reference style.css and app.js")

    style_tag = f'<link rel="stylesheet" href="style.css?v={content_hash(style)}">'
    script_tag = f'<script src="app.js?v={content_hash(script)}" defer></script>'
    html = html.replace('href="style.css"', f'href="style.css?v={content_hash(style)}"')
    html = html.replace('src="app.js"', f'src="app.js?v={content_hash(script)}"')

    # Same content hash for the vendored scripts; the preview inlines them by
    # the tag they end up with.
    vendor_tags = {}
    for name in VENDOR_SCRIPTS:
        reference = f'src="{VENDOR_DIR}/{name}"'
        if reference not in html:
            raise SystemExit(f"error: site/index.html must reference {VENDOR_DIR}/{name}")
        src = f'src="{VENDOR_DIR}/{name}?v={content_hash(vendor[name])}"'
        html = html.replace(reference, src)
        vendor_tags[f"<script {src} defer></script>"] = name

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
        # Language -> {bundle identifier -> {subtitle, description}}: the
        # site/i18n/ overlays the page applies on top of the catalog text.
        "i18n": i18n,
    }

    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "style.css").write_bytes(style)
    (out_dir / "app.js").write_bytes(script)
    vendor_out = out_dir / VENDOR_DIR
    vendor_out.mkdir(parents=True, exist_ok=True)
    for name, data in vendor.items():
        (vendor_out / name).write_bytes(data)
    shutil.copyfile(source_path, out_dir / "all-apps.json")
    shutil.copyfile(proxy_path, out_dir / "all-apps-proxy.json")
    (out_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    preview = build_preview(
        html, style, script, vendor, vendor_tags, source, config, style_tag, script_tag
    )
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
        *icon_names,
        "site.webmanifest",
        "all-apps.json",
        "all-apps-proxy.json",
        "config.json",
        "preview.html",
        *(f"{VENDOR_DIR}/{name}" for name in VENDOR_FILES),
    ):
        path = out_dir / name
        if path.is_file():
            print(f"  {display(path)}  {path.stat().st_size / 1024:.0f} KB")
    for lang, table in i18n.items():
        print(f"  i18n/{lang}.json: {len(table)} translated apps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
