#!/usr/bin/env python3
"""Render an AltStore "NEW UPDATE" promo image with Pillow — no SVG, no
rsvg-convert / qlmanage.

Draws the 1600x1200 (4:3) promo directly with ImageDraw/ImageFont: a diagonal
tint-tinted gradient, two soft radial glows, the app icon (rounded corners) and
its white stroke, the "NEW UPDATE" badge, and the app name + description in the
right column. Layout is computed from Pillow font metrics (exact per-glyph
widths), so the text always fits the column even with CJK strings.

Configuration comes from <out>/news.toml (see the template below); any CLI flag
overrides its news.toml counterpart. Colors left unset are derived into a
harmonious scheme:
  - tint / tint_alt   -> [app] / [source] tint_color
  - background        -> light shade of the icon's dominant color, so the
                         promo blends with the app's artwork; falls back to
                         a dark tint-derived base when the icon is unreadable
  - text_color        -> white (or black for light backgrounds)
  - tagline_color     -> derived from the background hue

The name's cap top lines up with the icon's top edge, and the description
wraps onto several lines (explicit newlines are honored) and is sized as
large as it can be without overflowing the right column or dropping below
the NEW UPDATE badge — so both columns share a vertical span and the promo
stays readable on a landscape phone and several fit per screen.

Text is drawn per glyph so each character uses the font for its script:
Helvetica for Latin, Hiragino Sans GB (W6/W3) for CJK, with letter-spacing
applied between glyphs. Fonts are loaded from macOS system paths; a clear
error is raised if none of them can be loaded.

Usage:
  render_news.py --out apps/PiliPlus           # everything from apps/PiliPlus/news.toml
  render_news.py --out apps/Apollo-Reborn \
    --tagline "New tagline"                  # CLI overrides news.toml

news.toml:
  name = "PiliPlus"
  tagline = "BiliBili 第三方客户端"            # "\n" in the value wraps too
  # Optional — unset colors are derived from config.toml:
  # [colors]
  # tint = "#73b480"             badge/glow accent (default: [app] tint_color)
  # tint_alt = "#00AEEF"         secondary accent (default: [source] tint_color)
  # background = "#0C111D"       dark gradient base (default: derived from tint)
  # text_color = "#FFFFFF"       app name color (default: auto white/black)
  # tagline_color = "#AABDD6"    subtitle color (default: derived from background)
"""

import argparse
import colorsys
import re
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

WIDTH, HEIGHT = 1600, 1200

# Left column geometry. The icon's left edge (x=150) is the layout's side
# margin; the name's cap top aligns with the icon's top edge (y=343), and the
# description's bottom must stay above the badge's bottom edge (857) — the
# description font is shrunk to enforce this.
ICON_X, ICON_Y, ICON_SIZE = 150, 343, 350
ICON_RADIUS = 88  # rounded-corner radius of the icon

# Right column geometry: text starts at x=640 and must stay inside the
# 1600-wide canvas with the same side margin as the icon's left edge — so the
# text's right edge and the icon's left edge sit an equal distance from the
# image borders. Short text stops earlier and leaves a larger gap, but never a
# smaller one than the icon's.
TEXT_X = 640
RIGHT_MARGIN = ICON_X
MAX_TEXT_WIDTH = WIDTH - RIGHT_MARGIN - TEXT_X  # 810
BADGE_X, BADGE_Y, BADGE_W, BADGE_H = 125, 773, 400, 84
BADGE_BOTTOM = BADGE_Y + BADGE_H  # 857
GAP_DESC = 40  # gap between the app name and the description

# Font-size caps. The name and description are fitted as large as they can be
# without overflowing the right column or the vertical space above the badge,
# so text stays readable when AltStore shows the image small.
NAME_MAX = 180
TAGLINE_MAX = 72
TAGLINE_MIN = 30  # floor for a pathologically long description
NAME_LETTER_SPACING = 1  # letter-spacing of the app name
BADGE_LETTER_SPACING = 6
BADGE_TEXT = "NEW UPDATE"
BADGE_TEXT_Y = 830  # baseline of the badge caption (matches the old template)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Font candidates per role, in preference order. Each is (path, ttc index);
# the first that loads is used. Helvetica covers Latin, Hiragino Sans GB (and
# the STHeiti fallback) cover CJK — one per style so the app name / badge can
# be bolder than the description.
FONT_CANDIDATES = {
    "latin": [
        ("/System/Library/Fonts/Helvetica.ttc", 0),  # Regular
    ],
    "latin_bold": [
        ("/System/Library/Fonts/Helvetica.ttc", 1),  # Bold
    ],
    "cjk": [
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),  # W3
        ("/System/Library/Fonts/STHeiti Medium.ttc", 1),  # Heiti SC Medium
    ],
    "cjk_bold": [
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),  # W6
        ("/System/Library/Fonts/STHeiti Medium.ttc", 0),  # Heiti TC Medium
    ],
}

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _load_font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """The first loadable font for ``kind`` at ``size``, cached per
    (kind, size). Fails with a clear message if no candidate loads."""
    key = (kind, size)
    font = _FONT_CACHE.get(key)
    if font is not None:
        return font
    for path, index in FONT_CANDIDATES[kind]:
        try:
            font = ImageFont.truetype(path, size, index=index)
            _FONT_CACHE[key] = font
            return font
        except OSError:
            continue
    tried = ", ".join(f"{p}#{i}" for p, i in FONT_CANDIDATES[kind])
    sys.exit(f"error: no loadable font for '{kind}' (tried: {tried})")


def _is_cjk(ch: str) -> bool:
    """CJK / full-width glyphs (Hiragana, Katakana, CJK ideographs, hangul…)."""
    return ord(ch) >= 0x2E80


def _font_for(ch: str, style: str, size: int) -> ImageFont.FreeTypeFont:
    """Font for one character: bold styles for the name/badge, regular for the
    description; each script picks its own Latin / CJK font."""
    if style == "bold":
        kind = "cjk_bold" if _is_cjk(ch) else "latin_bold"
    else:
        kind = "cjk" if _is_cjk(ch) else "latin"
    return _load_font(kind, size)


def measure_width(text: str, size: int, style: str) -> float:
    """Exact rendered width of ``text`` at ``size``: each glyph is measured
    with the font it will be drawn in, so mixed Latin + CJK is exact."""
    return sum(_font_for(ch, style, size).getlength(ch) for ch in text)


def cap_top_em(style: str) -> float:
    """Cap-top height above the baseline in ems, from a capital 'A' at size
    100 — used to line the app name's top edge up with the icon. The bbox is
    measured with anchor='ls' so it's relative to the baseline (as drawn)."""
    font = _load_font("latin_bold" if style == "bold" else "latin", 100)
    _left, top, _right, _bottom = font.getbbox("A", anchor="ls")
    return -top / 100.0


def fit_name_font(name: str) -> int:
    """Largest app-name font size that fits the right column (cap ``NAME_MAX``),
    using the exact measured width."""
    if not name:
        return NAME_MAX
    gaps = max(len(name) - 1, 0) * NAME_LETTER_SPACING
    width = measure_width(name, NAME_MAX, "bold") + gaps
    if width <= MAX_TEXT_WIDTH:
        return NAME_MAX
    # Glyph widths are proportional to font size for TrueType, so scale.
    return max(1, int((MAX_TEXT_WIDTH - gaps) * NAME_MAX / width))


def _longest_prefix(text: str, font: int, max_width: float) -> int:
    """Length of the longest prefix of ``text`` that fits ``max_width``."""
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure_width(text[:mid], font, "regular") <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return max(lo, 1)


def wrap_text(text: str, font: int, max_width: float) -> list[str]:
    """Split ``text`` into lines that fit ``max_width`` at ``font``.

    Explicit ``\\n`` always breaks a line; lines are additionally wrapped at
    whitespace, with long CJK runs / single words character-wrapped as a
    fallback. Keeps the description large and readable on several lines
    instead of shrinking it onto one.
    """
    lines: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        current = ""
        for word in para.split(" "):
            trial = f"{current} {word}" if current else word
            if measure_width(trial, font, "regular") <= max_width:
                current = trial
                continue
            if current:
                lines.append(current)
            current = word
            # A single token can still be wider than the column: break it up.
            while current and measure_width(current, font, "regular") > max_width:
                k = _longest_prefix(current, font, max_width)
                lines.append(current[:k])
                current = current[k:]
        if current:
            lines.append(current)
    return lines


def fit_tagline(tagline: str, max_height: float) -> tuple[list[str], int]:
    """The description wrapped onto lines and sized to fit ``max_height`` px.

    A short description stays on one line at full size when it fits; otherwise
    it's word-wrapped (explicit ``\\n`` always breaks). Wrapping — not
    shrinking — keeps the text large, but the whole block is also constrained
    to ``max_height`` so its bottom stays above the NEW UPDATE badge. Each
    line is measured exactly, so the font shrinks only when a line really
    overflows.
    """
    if not tagline.strip():
        return [], TAGLINE_MAX
    # Fast path: exact single-line fit at full size.
    if "\n" not in tagline and measure_width(tagline, TAGLINE_MAX, "regular") <= MAX_TEXT_WIDTH:
        font = max(TAGLINE_MIN, min(TAGLINE_MAX, int(max_height / 1.5)))
        return [tagline.strip()], font
    font = TAGLINE_MAX
    lines = wrap_text(tagline, font, MAX_TEXT_WIDTH)
    for _ in range(8):
        # 1) Horizontal: any line the real renderer would clip shrinks the font.
        worst = max((measure_width(l, font, "regular") for l in lines if l), default=0)
        if worst > MAX_TEXT_WIDTH:
            font = max(TAGLINE_MIN, int(MAX_TEXT_WIDTH * font / worst))
            lines = wrap_text(tagline, font, MAX_TEXT_WIDTH)
            continue
        # 2) Vertical: whole description must fit above the badge.
        if len(lines) * 1.5 * font <= max_height or font <= TAGLINE_MIN:
            break
        font = max(TAGLINE_MIN, int(max_height / (len(lines) * 1.5)))
        lines = wrap_text(tagline, font, MAX_TEXT_WIDTH)
    return lines, font


def _text_width_tracked(text: str, size: int, style: str, tracking: float) -> float:
    """Measured width including letter-spacing between glyphs."""
    if not text:
        return 0.0
    return measure_width(text, size, style) + tracking * (len(text) - 1)


def _draw_text(img: Image.Image, x: float, y: float, text: str, size: int,
               style: str, tracking: float, fill: tuple[int, int, int]) -> None:
    """Draw ``text`` left-aligned with baseline at ``(x, y)``, applying
    ``tracking`` px between glyphs and per-glyph Latin / CJK fonts."""
    draw = ImageDraw.Draw(img)
    for ch in text:
        font = _font_for(ch, style, size)
        draw.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += font.getlength(ch) + tracking


# ---------------------------------------------------------------------------
# Color helpers (all hex "#RRGGBB" in and out)
# ---------------------------------------------------------------------------

def _hex_to_hls(value: str) -> tuple[float, float, float]:
    hx = value.lstrip("#")
    r, g, b = (int(hx[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def _hls_to_hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02X}{:02X}{:02X}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )


def _hex_rgb(value: str) -> tuple[int, int, int]:
    hx = value.lstrip("#")
    return tuple(int(hx[i : i + 2], 16) for i in (0, 2, 4))


def check_hex(value: str, what: str) -> str:
    """Validate a #RRGGBB color from news.toml; return it normalized."""
    if not _HEX_RE.match(value):
        sys.exit(f"error: {what} must be #RRGGBB, got {value!r}")
    return value.upper()


def derive_background(tint: str) -> str:
    """Dark gradient base in the tint's hue: keep hue, tone saturation way
    down, pin lightness low — reads as a deep tint-tinted navy."""
    h, _l, s = _hex_to_hls(tint)
    return _hls_to_hex(h, 0.09, min(s * 0.6, 0.5))


def derive_light_background(color: str) -> str:
    """Soft light background from an icon color: keep the hue, push
    lightness high and saturation low — a pale tint the icon blends with."""
    h, _l, s = _hex_to_hls(color)
    return _hls_to_hex(h, 0.88, min(s, 0.35))


def derive_bg_stops(bg: str) -> tuple[str, str]:
    """Lighter mid-stop and darker end-stop of the background gradient.
    The ramp adapts to the base lightness: light backgrounds get a subtle
    ramp, dark ones the original stronger one."""
    h, l, s = _hex_to_hls(bg)
    if l > 0.55:
        return _hls_to_hex(h, min(l + 0.05, 0.97), s), _hls_to_hex(h, max(l - 0.08, 0.55), s)
    return _hls_to_hex(h, min(l + 0.08, 0.55), s), _hls_to_hex(h, max(l - 0.03, 0.03), s)


def auto_text_color(bg: str) -> str:
    """White on dark backgrounds, black on light ones."""
    _h, l, _s = _hex_to_hls(bg)
    return "#111111" if l > 0.55 else "#FFFFFF"


def derive_tagline_color(bg: str) -> str:
    """Tagline shade derived from the background: a light tint on dark
    backgrounds, a darker readable shade on light ones."""
    h, l, s = _hex_to_hls(bg)
    if l > 0.55:
        return _hls_to_hex(h, max(l - 0.35, 0.35), min(s + 0.15, 0.45))
    return _hls_to_hex(h, 0.72, min(s, 0.35))


def extract_icon_color(icon_path: Path) -> str | None:
    """Dominant colorful color of the app icon, for a light background.

    Downsamples the icon to 64x64 with Pillow (LANCZOS), buckets the pixels,
    and scores buckets by pixel count x (saturation - 0.15) so a light
    design's background color doesn't win over its colorful elements. Returns
    None when the icon can't be read or holds no usable color.
    """
    try:
        img = Image.open(icon_path).convert("RGBA").resize(
            (64, 64), Image.Resampling.LANCZOS
        )
    except (OSError, ValueError, SyntaxError):
        return None
    px = img.load()

    buckets: Counter = Counter()
    for y in range(64):
        for x in range(64):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            if (r > 235 and g > 235 and b > 235) or (r < 20 and g < 20 and b < 20):
                continue  # near-white / near-black (borders, glare, alpha void)
            buckets[(r // 16 * 16, g // 16 * 16, b // 16 * 16)] += 1

    if not buckets:
        return None
    total = sum(buckets.values())
    best, best_score = None, 0.0
    for (r, g, b), n in buckets.items():
        score = n * max(saturation(r, g, b) - 0.15, 0.0) / total
        if score > best_score:
            best, best_score = (r, g, b), score
    if best is None:
        return None
    return "#{:02X}{:02X}{:02X}".format(*best)


def saturation(r: int, g: int, b: int) -> float:
    """HSL saturation (0..1) of an RGB tuple."""
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 510
    if l == 0 or l == 1:
        return 0.0
    return (mx - mn) / (2 - mx / 255 - mn / 255) if l > 0.5 else (mx - mn) / (mx + mn)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _lerp_stops(s: float, stops: list[tuple[float, tuple[int, int, int]]]) -> tuple[int, int, int]:
    """Color of the gradient at coordinate ``s`` (0..1) across the stops."""
    if s <= stops[0][0]:
        return stops[0][1]
    for (o1, c1), (o2, c2) in zip(stops, stops[1:]):
        if s <= o2:
            t = (s - o1) / (o2 - o1) if o2 > o1 else 1.0
            return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))
    return stops[-1][1]


def _compose_radial(img: Image.Image, cx: float, cy: float, rx: float, ry: float,
                    color: tuple[int, int, int], peak: float) -> None:
    """Overlay a soft radial glow: alpha ``peak`` at the center, fading linearly
    to 0 at the ellipse edge. Computed small (256x256) and upscaled."""
    N = 256
    layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    lp = layer.load()
    for j in range(N):
        for i in range(N):
            x = i / (N - 1) * WIDTH
            y = j / (N - 1) * HEIGHT
            d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if d >= 1:
                continue
            a = int(peak * (1 - d**0.5) * 255)
            lp[i, j] = (color[0], color[1], color[2], a)
    img.alpha_composite(layer.resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR))


def _base_canvas(colors: dict) -> Image.Image:
    """Opaque RGBA canvas: diagonal 3-stop gradient plus the two tint glows."""
    stops = [(0.0, colors["bg"]), (0.55, colors["bg_mid"]), (1.0, colors["bg_dark"])]
    N = 256
    g = Image.new("RGB", (N, N))
    gp = g.load()
    for j in range(N):
        for i in range(N):
            s = (i + j) / (2 * (N - 1))
            gp[i, j] = _lerp_stops(s, stops)
    img = g.resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR).convert("RGBA")
    _compose_radial(img, 0.30 * WIDTH, 0.50 * HEIGHT, 0.75 * WIDTH / 2, 0.75 * HEIGHT / 2,
                    colors["tint"], 0.30)
    _compose_radial(img, 0.78 * WIDTH, 0.85 * HEIGHT, 0.80 * WIDTH / 2, 0.80 * HEIGHT / 2,
                    colors["tint_alt"], 0.22)
    return img


def _draw_circles(img: Image.Image) -> None:
    """The two faint decorative circles near the corners (white, ~5% opacity)."""
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    white = (255, 255, 255, 13)
    d.ellipse([1600 - 300, -300, 1600 + 300, 300], outline=white, width=2)
    d.ellipse([-340, 1200 - 340, 340, 1200 + 340], outline=white, width=2)
    img.alpha_composite(layer)


def _draw_icon(img: Image.Image, icon_path: Path) -> None:
    """Paste the icon center-cropped (aspect-fill) into its rounded-corner
    slot, then draw the thin white border around it."""
    try:
        src = Image.open(icon_path).convert("RGBA")
    except (OSError, ValueError, SyntaxError):
        sys.exit(f"error: cannot read icon: {icon_path}")
    w, h = src.size
    scale = max(ICON_SIZE / w, ICON_SIZE / h) if w and h else 1.0
    src = src.resize(
        (round(w * scale), round(h * scale)), Image.Resampling.LANCZOS
    )
    left = (src.width - ICON_SIZE) // 2
    top = (src.height - ICON_SIZE) // 2
    src = src.crop((left, top, left + ICON_SIZE, top + ICON_SIZE))

    # Mask = rounded-corner shape AND the icon's own alpha, so transparent
    # padding inside the icon (common for square app icons) stays transparent.
    mask = Image.new("L", (ICON_SIZE, ICON_SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, ICON_SIZE - 1, ICON_SIZE - 1], radius=ICON_RADIUS, fill=255
    )
    mask = ImageChops.multiply(mask, src.getchannel("A"))
    img.paste(src, (ICON_X, ICON_Y), mask)

    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [ICON_X, ICON_Y, ICON_X + ICON_SIZE - 1, ICON_Y + ICON_SIZE - 1],
        radius=ICON_RADIUS, outline=(255, 255, 255, 56), width=4,
    )
    img.alpha_composite(layer)


def _draw_badge(img: Image.Image, colors: dict) -> None:
    """The NEW UPDATE pill below the icon, plus its tracked caption."""
    tint = colors["tint"]
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        [BADGE_X, BADGE_Y, BADGE_X + BADGE_W - 1, BADGE_Y + BADGE_H - 1],
        radius=BADGE_H // 2, fill=(*tint, 46), outline=(*tint, 153), width=3,
    )
    img.alpha_composite(layer)

    total = _text_width_tracked(BADGE_TEXT, 44, "bold", BADGE_LETTER_SPACING)
    x = BADGE_X + (BADGE_W - total) / 2
    _draw_text(img, x, BADGE_TEXT_Y, BADGE_TEXT, 44, "bold",
               BADGE_LETTER_SPACING, tint)


def _draw_layout(img: Image.Image, name: str, name_font: int, name_y: float,
                 tag_lines: list[str], tag_ys: list[float], tagline_font: int,
                 colors: dict) -> None:
    """Right column: the app name (top aligned to the icon) and the wrapped
    description lines, each on its own baseline."""
    _draw_text(img, TEXT_X, name_y, name, name_font, "bold", NAME_LETTER_SPACING,
               colors["text_color"])
    for line, y in zip(tag_lines, tag_ys):
        _draw_text(img, TEXT_X, y, line, tagline_font, "regular", 0,
                   colors["tagline_color"])


def load_configs(out: Path) -> tuple[dict, dict]:
    """``news.toml`` and the app's ``config.toml`` as raw dicts ({} if absent
    or unreadable)."""
    news: dict = {}
    path = out / "news.toml"
    if path.exists():
        try:
            with open(path, "rb") as f:
                news = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            sys.exit(f"error: {path}: invalid TOML: {exc}")
    cfg: dict = {}
    path = out / "config.toml"
    if path.exists():
        try:
            with open(path, "rb") as f:
                cfg = tomllib.load(f)
        except tomllib.TOMLDecodeError:
            pass  # not ours to parse — just skip the tint defaults
    return news, cfg


def main() -> None:
    ap = argparse.ArgumentParser(description="Render AltStore news promo image")
    ap.add_argument("--name", help="app display name (default: news.toml)")
    ap.add_argument("--tagline", help="short one-line descriptor (default: news.toml)")
    ap.add_argument("--icon", default="icon.png", help="icon path, relative to --out dir")
    ap.add_argument("--tint", help="badge/glow accent color (default: config.toml [app] tint_color)")
    ap.add_argument("--tint-alt", help="secondary accent color (default: config.toml [source] tint_color)")
    ap.add_argument("--out", required=True, help="output directory (the app folder, e.g. apps/PiliPlus)")
    args = ap.parse_args()

    out = Path(args.out)
    news, cfg = load_configs(out)
    colors = news.get("colors", {}) or {}

    name = args.name or news.get("name")
    if not name:
        sys.exit("error: no app name (pass --name or set name in news.toml)")
    tagline = args.tagline or news.get("tagline") or ""

    app_tint = (cfg.get("app", {}) or {}).get("tint_color")
    src_tint = (cfg.get("source", {}) or {}).get("tint_color")
    tint = args.tint or colors.get("tint") or app_tint or "#73B480"
    tint_alt = args.tint_alt or colors.get("tint_alt") or src_tint or tint

    # Background: explicit news.toml value, else a light shade derived from
    # the app icon's dominant color, else a dark tint-derived base. The
    # gradient stops, name color and tagline color derive from it (each
    # stop can be pinned individually in news.toml).
    bg = colors.get("background")
    if bg is None:
        icon_color = extract_icon_color(out / args.icon)
        bg = derive_light_background(icon_color) if icon_color else derive_background(tint)
    bg = check_hex(bg, "background")
    derived_mid, derived_dark = derive_bg_stops(bg)
    bg_mid = check_hex(colors.get("bg_mid") or derived_mid, "bg_mid")
    bg_dark = check_hex(colors.get("bg_dark") or derived_dark, "bg_dark")
    text_color = check_hex(colors.get("text_color") or auto_text_color(bg), "text_color")
    tagline_color = check_hex(
        colors.get("tagline_color") or derive_tagline_color(bg), "tagline_color"
    )

    # Layout the right column: the name's cap top lines up with the icon's top
    # edge, and the description (possibly several wrapped lines) is sized so
    # its bottom stays above the NEW UPDATE badge's bottom edge.
    name_font = fit_name_font(name)
    name_y = ICON_Y + cap_top_em("bold") * name_font
    name_bottom = name_y + 0.25 * name_font  # descender, conservative
    desc_space = BADGE_BOTTOM - name_bottom - GAP_DESC

    tag_lines, tagline_font = fit_tagline(tagline, desc_space)
    line_h_tag = 1.5 * tagline_font
    tag_ys = [
        name_bottom + GAP_DESC + (i + 0.8) * line_h_tag for i in range(len(tag_lines))
    ]

    draw_colors = {
        "bg": _hex_rgb(bg),
        "bg_mid": _hex_rgb(bg_mid),
        "bg_dark": _hex_rgb(bg_dark),
        "tint": _hex_rgb(tint),
        "tint_alt": _hex_rgb(tint_alt),
        "text_color": _hex_rgb(text_color),
        "tagline_color": _hex_rgb(tagline_color),
    }

    png_path = out / "images" / "news.png"
    png_path.parent.mkdir(parents=True, exist_ok=True)
    img = _base_canvas(draw_colors)
    _draw_circles(img)
    _draw_icon(img, out / args.icon)
    _draw_badge(img, draw_colors)
    _draw_layout(img, name, name_font, name_y, tag_lines, tag_ys, tagline_font,
                 draw_colors)
    img.convert("RGB").save(png_path, format="PNG")

    size = png_path.stat().st_size
    print(f"wrote {png_path} ({size/1024:.0f} KiB)")


if __name__ == "__main__":
    main()
