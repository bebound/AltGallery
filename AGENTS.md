# AltGallery — Agent Guide

## Project Goal

Generate AltStore sources (`apps.json`) for IPA projects on GitHub.

- Generator: Python **AltGen**, invoked via `uvx altgen`

## Tools are uv scripts

Every script in `tools/` is a [uv script](https://docs.astral.sh/uv/guides/scripts/):
an executable with an inline PEP 723 metadata block that names its own Python
version and dependencies, so `uv run` resolves and caches them — no venv to
create or activate first.

```bash
uv run tools/render_news.py --out apps/PiliPlus   # Pillow from the inline metadata
uv run tools/make_proxy.py                        # stdlib only, nothing installed
```

Run them from the repo root (they resolve paths against the working
directory), and always through `uv run` — never `python3 tools/…`, which skips
the metadata and fails on any script that needs a dependency. `requirements.txt`
stays only as a record of the same versions for anyone who prefers a
conventional `.venv`; it is not needed to run the tools.

## Commits

Never ask the user whether to commit — the user commits everything
themselves. Do not run `git add`, `git commit`, or `git push` on your own
initiative, and do not end a turn with "shall I commit this?" either.

Leaving your changes in the working tree is the expected end state: report
what changed (files touched, what was regenerated) and stop there. This
applies to generated files too (`apps.json`, `all-apps.json`,
`images/news.webp`) — never commit them, and never ask about committing them.

## Comments

Write comments in English. Any comment you add or modify in code
(`config.toml`, Python, shell scripts, etc.) must be written in English —
never in Chinese or other languages.

## Reading JSON

Prefer `jq` to read or inspect JSON files (`apps.json`, `all-apps.json`), e.g.
`jq '.apps | length' PiliPlus/apps.json` or `jq '.apps[0]' PiliPlus/apps.json`.
Only read the full file when you actually need the whole content.

## Directory Layout

Each IPA gets its own folder under `apps/`, e.g. `apps/PiliPlus/`:

```
apps/<AppName>/
├── config.toml      # altgen configuration file
├── news.toml        # news image config (name, tagline, optional colors)
├── icon.webp        # app icon (converted to WebP — see Icon Format)
├── images/          # screenshots + news.webp promo image
│   ├── home.webp    # screenshot, listed in [app] screenshots (converted to WebP)
│   └── news.webp    # generated promo image (referenced from [news] image_url)
└── apps.json        # generated AltStore source (gitignored), do not hand-edit
```

Each folder's `apps.json` is an independent AltStore source.

## Generating apps.json

`./update.sh` regenerates every app source and merges them into
`all-apps.json`. After editing a `config.toml`, regenerate just that app to
verify it — you don't need to update the other apps locally (the CI workflow
regenerates and commits everything on push):

```bash
./update.sh <AppName>                            # single app — enough for local verification
cd apps/<AppName> && uvx altgen -c config.toml   # equivalent, lower-level; note: config.toml, not config.json
```

altgen reads the GitHub Releases API; if rate-limited or the repo is private,
pass a token (`--token` > `GITHUB_TOKEN` env > `[github].token` in
config.toml).

**Rule: after ANY `config.toml` change, regenerate — never leave the two out
of sync, and never hand-edit `apps.json`.**

`.github/workflows/update.yml` regenerates and commits `apps.json` and
`all-apps.json` on every push to `master`, every 6 hours, and on manual
`workflow_dispatch`. (Both files are tracked despite `.gitignore`, so leave
any local regenerated changes for the workflow to commit.)

The same workflow then writes `all-apps-proxy.json`, a mirror of
`all-apps.json` built by `tools/make_proxy.py`: the URLs AltStore actually
fetches — `raw.githubusercontent.com` files (icons, screenshots, news images)
and `github.com/<owner>/<repo>/releases/download/...` ipas — are prefixed with
`https://gh-proxy.com/` so the source also works where GitHub is unreachable.
GitHub *pages* (`website`, `news[].url`, `/releases/tag/...` links in text)
are left untouched. It is generated from `all-apps.json` only — never edit it
by hand, and do not regenerate it locally when adding or updating an app: the
update workflow writes both `all-apps-proxy.json` and every per-app
`apps/<AppName>/apps-proxy.json` after each push. Run
`uv run tools/make_proxy.py` only when you specifically want to inspect what
the mirror will contain.

## Merging into all-apps.json

After all app sources are regenerated, merge them into the repo-root
`all-apps.json` (the "ultimate" AltStore source for the whole project).
The whole flow — regenerate every source, then merge — is scripted in
`./update.sh` (run from anywhere); prefer it over the individual commands.

```bash
uvx altgen merge -c assets/merge.toml apps/<AppName>/apps.json ...
```

Pass **every** `apps/<AppName>/apps.json` in the repo as an input. The merge
config lives in `assets/merge.toml`: merge mode only reads `[source]` (root
metadata: name, icon_url, tint_color) and `[output]` (`path = "../all-apps.json"`,
resolved against the config's directory → repo root).

**Rule: after any `config.toml` change, regenerate with `./update.sh
<AppName>` and check the diff — never leave `config.toml` and its `apps.json`
out of sync. You don't need the full `./update.sh` locally: `apps.json` and
`all-apps.json` are regenerated and committed by the CI workflow on every push
to `master`, so a single-app run is enough to verify the sources. (Both files
are tracked despite `.gitignore`, so a local regenerate shows them as modified
in `git status` — leave them for the workflow to commit.) To refresh them
immediately, run the `Update all-apps.json` workflow manually
(`workflow_dispatch`).**

## GitHub Pages Site

The public catalog at https://altgallery.fromkk.com/ is a static page
built from the generated sources:

- `site/index.html`, `site/style.css`, `site/app.js` — the page. It fetches
  `all-apps.json` (served beside it) at runtime and renders every image —
  logos, icons, screenshots — from a copy under `media/`, so the
  site hosts its own artwork and only links (release pages, ipa downloads,
  AltStore sources) point at GitHub. The Direct/Mirror switch rewrites those
  links through gh-proxy.com and subscribes to the prepared
  `apps/<App>/apps-proxy.json` sources.
- `site/vendor/` — the Embla carousel the "recently updated" rail runs on
  (`embla-carousel` + `embla-carousel-auto-scroll`, MIT, notice beside them).
  Vendored as UMD builds instead of loaded from a CDN: the site keeps serving
  its own assets, and `preview.html` still runs from `file://`. The rail is one
  card per newest app with Embla looping the strip and the auto-scroll plugin
  drifting it at `RECENT_SPEED` (px per second). The plugin owns the pause and
  resume: `stopOnInteraction` is off so it stops on `pointerDown` and comes back
  `RECENT_RESTART_MS` after the strip settles (`startDelay`), and `stopOnFocusIn`
  is the plugin's own keyboard handling. Only the states it cannot see are
  `site/app.js`'s business (`railParked` / `syncRailAuto`): a pointer hovering the
  rail, a finger on the strip, the app sheet, off screen, a background tab and
  `prefers-reduced-motion`. Do not call `reInit()` on a window resize — it is a
  hard reset that snaps the strip to the nearest card, and Embla re-measures
  itself; a resize only refits the promo names. Replacing the rail means
  replacing those three files' worth of wiring, so bump the version there rather
  than editing the vendored bundles. A language switch rebuilds the strip to
  re-label it and restores the reader's place afterwards; the Direct/Mirror
  switch only rewrites the subscription hrefs in place, so the rail and the grid
  are never torn down for it.
- The app sheet owns a history entry: opening one pushes `#app=<bundle id>`, so
  the back button and the iOS edge swipe close the sheet instead of leaving the
  page, and that hash also works as a deep link. While it is open the page
  behind it is `inert` (`aria-modal` alone is not honoured everywhere).
- `site/i18n/zh.json` — the Chinese `subtitle` / `description` the page shows
  while the language switch is on 中文, keyed by bundle identifier. It exists
  because an AltStore source carries exactly one language per app
  (`localizedDescription` is a plain string, with no per-locale variants), so
  the Chinese text cannot live in `apps.json` without taking the original away
  from English readers. `tools/build_site.py` folds every
  `site/i18n/<lang>.json` into the generated `config.json`, so the page still
  makes one data request. Both fields translate the matching `config.toml`
  `[app]` field — the `subtitle` here is the short one-liner, **not** the
  longer `README_CN.md` line. **An app with no entry keeps its catalog text**
  — which is already Chinese for the Chinese-only projects — so the file only
  covers apps whose catalog text is English, and a missing entry is never a
  bug. Keep it in sync when moving an app (the key is its bundle identifier);
  search matches every language, so a Chinese query finds an English app.
- `tools/build_site.py` — validates `all-apps-proxy.json` against
  `all-apps.json` (the proxy prefix is derived from the mirror), checks that
  every per-app source exists, stages every displayed image from the working
  tree into `_site/media/`, writes a generated `config.json` (the raw URL
  prefixes, `mediaBase` and `mediaFiles`, which the page uses to map a raw URL
  to its local copy, plus the `i18n` overlays), and stages the split site plus
  both JSON files. Content hashes are added to the CSS/JS references only.
  `site/vendor/` is staged beside the page with the same content hashes, and
  the vendored scripts are inlined into `preview.html` ahead of `app.js`.

  The site's own icons are all drawn from the catalog logo, one file per
  surface that shows one: `_site/favicon.ico` (16/32/48 px frames),
  `_site/favicon-16x16.png` / `-32x32.png` / `-96x96.png` (the 96 is a
  multiple of 48, which is all Google Search draws as a favicon),
  `_site/apple-touch-icon.png` (180×180, the iOS home screen),
  `_site/web-app-manifest-192x192.png` / `-512x512.png` and
  `_site/maskable-512x512.png` for the `_site/site.webmanifest` that
  Chrome/Android and Edge install from. The tab icons keep the logo's
  transparent rounded corners; the touch icon and the maskable copy are
  flattened onto the catalog tint instead — iOS paints an alpha channel black
  on the home screen, and a maskable icon must have no transparent pixel at
  all, since Android cuts the launcher's shape out of it. `favicon.ico` is
  also the file that clients which never read the page (feed readers,
  bookmark managers, link previews, crawlers) request by name. Every icon
  link is relative, so `preview.html` finds them beside itself as well.

  Staged images are optimized for the size they render at, which is where most
  of the page's weight went: app icons are resized to 128×128 (the largest CSS
  box is 84px, so 128 still covers a 2× display) and the site logo to 256×256,
  screenshots are capped at 800px tall, and everything is re-encoded to WebP
  and kept only when that is smaller than the original bytes — the constants
  at the top of the script set each budget. An embedded ICC profile (most
  screenshots are Display P3) is carried into the WebP, so colours do not
  shift. Because the extension usually changes, `config.json`'s `mediaFiles`
  maps each repository path to the file actually staged; a file that stays in
  its original format keeps its path. Needs Pillow and tqdm, which the script's
  inline PEP 723 metadata names, so `uv run` installs them — not stdlib only.
  Staging prints a tqdm bar on stderr (the re-encode is the slow part of a
  build); it turns itself off when stderr is not a terminal, so CI logs keep
  just the `Staged N display images` line, and the warnings the loop collects
  are printed after the bar clears instead of being painted over.
- Search & link previews. The page is a single JavaScript-rendered document,
  which is why the shell itself has to carry the text Google reads: the
  `meta description`, `<title>` and the hero copy are written out in
  `site/index.html` (English, matching what `app.js` sets for `en`), not left
  empty for the script to fill. On top of that the shell carries a
  `<link rel="canonical">`, an `og:`/`twitter:` set with `_site/og.png`
  (drawn by `build_site.py`, 1200×630, no screenshot), and a `WebSite`
  JSON-LD block. **That block is what makes Google show "AltGallery" instead
  of the domain-level `fromkk.com`:** site names are resolved per domain and
  per subdomain, and only the subdomain's own home page can claim one. Its
  `url` must be `SITE_URL`, which is also the canonical and the address
  `robots.txt` / `sitemap.xml` are generated for — one constant at the top of
  `build_site.py`, and the build refuses to run if the page's canonical
  disagrees with it. `_site/robots.txt` allows everything (the CSS/JS carry
  `?v=` hashes, so no rule may match a query string) and advertises the
  sitemap; `_site/sitemap.xml` lists the home page alone, because an app is a
  `#app=` sheet and a fragment is not an indexed URL. The favicon follows the
  same per-hostname rule: `favicon-96x96.png` (96 is a multiple of 48, the
  smallest size Google Search draws) is declared first, and nothing is
  disallowed — Googlebot-Image has to be able to fetch it.
- A `<noscript>` block at the end of the library is the catalog's static
  copy: `build_site.py` fills `#noscript-catalog` with every app as a link to
  its GitHub release page plus its subtitle, so a reader or crawler without
  JavaScript still gets the 103 apps as text. It also forces `[data-reveal]`
  visible, since the reveal observer lives in `app.js`.
- `.github/workflows/pages.yml` — builds and deploys only when the update
  workflow finishes (an update run triggered by the push, including the
  bot's own commits, which never trigger `push` workflows), plus manual
  dispatch, so one push creates a single Pages deployment record. The
  repository's Pages source must be set to "GitHub Actions".
- `.github/workflows/pages-cloudflare.yml` — the same build, deployed to a
  Cloudflare Pages project (name and production branch in its `env`) with
  `cloudflare/wrangler-action@v4`, on the same triggers. It needs the
  `CLOUDFLARE_API_TOKEN` (Cloudflare Pages: Edit) and `CLOUDFLARE_ACCOUNT_ID`
  repository secrets, and the Pages project must be a Direct Upload one — a
  Git-connected project is built by Cloudflare itself instead, and cannot be
  deployed from here.

The build also writes `_site/preview.html`, with CSS, JS and the catalog
inlined; it draws images from `_site/media/`, so it opens straight from disk
as long as it stays beside that directory:

```bash
uv run tools/build_site.py
open _site/preview.html          # local preview, no server
python3 -m http.server -d _site  # or serve the real split page
```

`_site/` is gitignored and never committed. It is host-agnostic — the page
fetches `all-apps.json` and `config.json` from its own directory and draws
every image from `media/` beside it — so the identical build serves both the
GitHub Pages and the Cloudflare Pages deployment. Serving its own images is
what lets a CDN in front of the site (Cloudflare Polish, for one) cache and
convert them; `media/` mirrors the repository layout (with a `.webp`
extension where an image was re-encoded), so a changed image is the same URL
with revalidation.

`tools/build_site.py` is a **preview tool, not a verification step**: adding or
updating an app never requires running it (or `tools/make_proxy.py`) locally.
Both Pages workflows rebuild from the committed sources after the update
workflow finishes, so any mistake in `site/i18n/zh.json` — a key that matches
no bundle identifier, say — surfaces there, not in a local run. Build locally
only when you actually want to look at the page.

## Generating News Images

Each app has a shared `news.webp` ("NEW UPDATE" — icon, name, tagline)
referenced by all its news entries via `[news] image_url`. Re-render every
app's image (from each app's `news.toml`: `name`, `tagline`, optional
`[colors]`) with:

```bash
./update_news.sh
```

or a single app with `uv run tools/render_news.py --out apps/<AppName>`.
Unset colors are auto-derived from `config.toml` tints and the icon's dominant
color (Pillow comes from the script's inline metadata, so there is nothing to
install first — no external rasterizer either). The icon is found by stem, so
`icon.png` and `icon.webp` both work with no flag (see [Icon
format](#icon-format)). The rendered
`apps/<AppName>/images/news.webp` stays in the working
tree — the URL in `config.toml` `[news] image_url` already points at it. Do
not auto-commit it.

The promo is written as a **lossy WebP (`NEWS_WEBP_QUALITY = 90`)**, not a
PNG: the artwork is a smooth gradient with large type, so q90 lands at about a
third of the PNG's bytes (159 → 43 KiB per image, ~12 → ~3.4 MiB across the
gallery) at a PSNR around 44 dB, and every subscriber downloads that file from
`raw.githubusercontent.com`. A `news.png` left behind by an older render is
deleted on the next run, and a new app's `[news] image_url` must end in
`news.webp` — the site's `media/` copy is unaffected either way, since
`tools/build_site.py` re-encodes display images regardless of their source
format.

### The tagline

`tagline` is the **abbreviated form of `subtitle` drawn on the image**, not a
copy of it: the app name is the image's headline, so the tagline carries the
part of the subtitle the name does not already say.

- It still has to answer "what is this app". A name that does not spell out
  the category ("PSX3IOS", "MeloX") needs the category right under it
  ("PlayStation 3 emulator"); a name that spells it out ("Aidoku") can drop
  it. Only words the name already carries are redundant ("iOS/iPadOS" under an
  `…iOS` name) — being informative beats being terse.
- Language: the app's own language, same as `subtitle`.
- Length: full size (72px) on **at most two lines**. When it does not fit,
  drop words — `fit_tagline()` would otherwise shrink the text silently, and
  that one image would just look smaller than every other app's.
- Differing from `subtitle` is fine and expected; *contradicting* it is the
  bug.
- An explicit `\n` in the value chooses the break point, which is how a
  two-line tagline avoids a bad wrap ("Open-source\nmanga reader", not
  "Open-source manga / reader").
- Re-read it whenever `subtitle` / `description` changes, so the two never
  drift apart.

Measure it — nothing is rendered and no file is written; a `font` below 72 or
more than two lines means the tagline is too long:

```bash
PYTHONPATH=tools uv run --python 3.11 --with pillow python3 -c "
import tomllib, render_news as R
n = tomllib.load(open('apps/<AppName>/news.toml','rb'))
f = R.fit_name_font(n['name']); nb = R.ICON_Y + R.cap_top_em('bold')*f + 0.25*f
print(R.fit_tagline(n.get('tagline',''), R.BADGE_BOTTOM - nb - R.GAP_DESC))"
```

## Icon Color Sampling (PIL)

Sampling a dominant color from an icon — for a new app's `tint_color`, or the
news background derived by `render_news.py` — is already implemented in
`tools/render_news.py` → `extract_icon_color()` (it downsamples the icon
with Pillow and buckets the pixels). Just call it:

```bash
PYTHONPATH=tools uv run --python 3.11 --with pillow python3 -c \
  "from render_news import extract_icon_color; from pathlib import Path; \
   print(extract_icon_color(Path('apps/<AppName>/icon.webp')))"
```

Substitute the app's real icon file name: `icon.webp` for anything added or
updated since the WebP rule, `icon.png` for an app that predates it.

**Importing a tool as a module means recreating what its inline metadata would
do**: `--python 3.11` matches its `requires-python` (the script uses
`tomllib`), `--with pillow` supplies its dependency, and `PYTHONPATH=tools`
puts it on the import path — the system `python3` alone raises
`ModuleNotFoundError: No module named 'PIL'`. Running the script itself is the
same thing without the ceremony: `uv run tools/render_news.py …`.

When a new app lacks an official tint, use the result as `[app] tint_color`
(brand color) — but eyeball the icon first: a multi-color or pale icon may
not have an obvious single brand color, so the sample needs human
confirmation.

### Deciding the tint — one histogram, then stop

The sample plus the icon's dominant colours settle it in one call; nothing
afterwards can change the answer, so nothing afterwards is worth running.

```bash
PYTHONPATH=tools uv run --python 3.11 --with pillow python3 -c "
from PIL import Image; from collections import Counter
im = Image.open('apps/<AppName>/icon.webp').convert('RGB').resize((64, 64))
for col, n in Counter(im.get_flattened_data()).most_common(8):
    print('#%02X%02X%02X' % col, n)"
```

Branch once:

- **One saturated colour next to black/white** — that colour is the brand
  tint. Pin it, move on.
- **Greys only** — the icon is monochrome and has no brand colour to
  recover. Pin a neutral grey scale in `news.toml` and move on:
  `tint` / `tint_alt` the near-black of the mark, `background` / `bg_mid` /
  `bg_dark` a light grey ramp, `tagline_color` a mid grey. `apps/Iridium/`,
  `apps/iPadn/` and `apps/Orca/` are the worked examples, each with a comment
  saying why it is pinned.
- **Two saturated colours** — genuinely ambiguous, the one case worth asking
  the user about.

⚠️ **A monochrome mark means the project has no brand colour — do not go
looking for one.** Searching the upstream website, the desktop `main.css`,
`mobile-theme.ts`, the logo SVG or the app's asset catalog after the
histogram already said "greys only" cannot change the answer; it only defers
a decision the histogram has made. Orca's black-on-white icon cost 28 shell
calls of exactly this search and still ended on a pinned neutral grey.

### Icon format

`icon.webp` is what the gallery stores: an icon is converted with
`tools/to_webp.py` before `render_news.py` runs (see [Converting Artwork to
WebP](#converting-artwork-to-webp)). A WebP master keeps a hi-res icon at a
fraction of the PNG bytes, and AltStore, the site and `render_news.py` all
read whatever format the URL serves.

Keep the stem `icon` and the extension real, and point both `icon_url` fields
in `config.toml` at the actual file (`.../apps/<AppName>/icon.webp`), since
altgen copies the URL verbatim.

`tools/render_news.py` resolves the stem itself (`resolve_icon()`): with no
`--icon` it picks the first of `icon.png` / `icon.webp` / `icon.jpg` /
`icon.jpeg` that exists, so `./update_news.sh` needs no per-app flag; passing
`--icon <file>` uses that file when it exists, else its stem is resolved the
same way. When importing `extract_icon_color()` by hand (above), substitute
the app's real file name — a `.png` path for what is now `icon.webp` just
returns `None` and silently falls back to the tint-derived background.

## Exploration Cost

A session's cost here is dominated by the fixed prefix, not by any single
tool call: the system prompt, AGENTS.md, an invoke-time skill and the tool
schemas are all re-read on **every** request (as cache reads). Measured on
the Orca add: ~96 tool calls became 192 requests, the ~35k-token prefix was
re-read 192 times, and ~50% of all input tokens went to that prefix alone.
Fewer, larger requests beat smaller, many requests.

- **Batch independent probes** into one Bash call — one `curl … | jq` over
  several endpoints, one `for` loop over `apps/*/config.toml` — instead of
  one call per question.
- **Don't re-poll.** After a successful `git status` or fetch, use the result
  in hand rather than asking again to confirm.
- **Decide from the cheapest signal.** A histogram, a `jq` field or a file
  extension usually settles what a repo tour would only defer.
- **Stop when the answer is on the table.** Exploration that can no longer
  change the decision is pure cost — see [Deciding the
  tint](#deciding-the-tint--one-histogram-then-stop) for the canonical trap.

## Reading an IPA's Bundle ID

`[app] bundle_identifier` must be the **real** identifier — never invent one
(`com.example.*` is a placeholder). Read it from a release ipa when no AltStore
source provides it:

```bash
curl -sL "https://api.github.com/repos/<owner>/<repo>/releases/latest" \
  | jq -r '.assets[] | select(.name|endswith(".ipa")) | .browser_download_url' | head -1
uv run tools/ipa_bundle_id.py App.ipa            # com.example.App
uv run tools/ipa_bundle_id.py App.ipa --json     # + name, version, build, min_os_version
```

Stdlib only — the inline metadata declares no dependencies, so nothing is
installed. stdout is the identifier alone, notes go to stderr, exit 1 when
unreadable. Several
`Payload/*.app` bundles → the `CFBundlePackageType = APPL` one wins (Flutter
ships as `Runner.app`, which never matches the ipa's filename); nested
`PlugIns/`/`Watch/` bundles are ignored. Its `min_os_version` is what the
binary really needs, and it may contradict `config.toml`.

## Extracting the App Icon from an IPA

Only when the project has **no** icon to download (nothing in the repo, README,
`assets/`, or its AltStore source):

```bash
uv run tools/ipa_icon.py App.ipa --list                     # candidates: size + file name
uv run tools/ipa_icon.py App.ipa --out apps/<AppName>/icon.png
uv run tools/to_webp.py apps/<AppName>/icon.png             # store it as icon.webp
```

Takes the largest icon the bundle lists (`CFBundleIcons`/`CFBundleIconFiles`,
matched against `<Entry>@2x.png` / `@3x` / `~ipad` files, plus any
`*icon*.png`); nested `PlugIns/`/`Watch/` bundles are ignored, so a Watch
app's bigger icon never wins. It also reads the app's **`Assets.car`**, the
compiled asset catalog — that is where the 1024x1024 ("marketing") artwork
usually lives, as LZFSE-compressed raw pixels rather than an image, while the
bundle only carries 120/152 loose files. The catalog is a BOMStore whose block
table names each rendition (`Icon-App-1024x1024@1x.png`); the tool walks it,
decompresses the LZFSE streams and re-encodes them as a standard PNG. It
prefers square renditions named like an icon, because a catalog also holds
launch images and other artwork. Writes the raw square artwork — `render_news.py`
rounds it at draw time — and refuses to overwrite an icon without `--force`.

Apple's **CgBI** PNGs (BGRA, premultiplied, raw-deflate) break Pillow, so the
tool decodes them to a standard PNG that `render_news.py` can read; plain
PNGs/JPEGs are copied as-is.

## Converting Artwork to WebP

All of an app's artwork is stored as WebP — the icon and the screenshots,
whether they were downloaded upstream or supplied by hand:

```bash
uv run tools/to_webp.py apps/<AppName>/icon.png apps/<AppName>/images/*
```

Each file keeps its stem and becomes `<stem>.webp`; the original is deleted
once the WebP is written. A file named `icon` is encoded lossless-or-q92
(whichever is smaller), everything else q82 — the settings
`tools/build_site.py` serves. An embedded ICC profile survives (most
screenshots are Display P3), and the resolution is left alone: a 1024 icon
stays 1024. An already-WebP file is skipped, so a rerun is harmless.

Because the extension changes, every reference must name the new file: both
`icon_url` fields and the README heading, and each `[app] screenshots` entry
(`images/home.webp`, not `images/home.png`).

⚠️ Convert the icon **before** rendering news: `render_news.py` finds the
icon by stem, so it reads `icon.webp` by itself once the conversion ran (see
[Icon format](#icon-format)).

## Screenshots

Screenshots live in `apps/<AppName>/images/` and are listed by URL in
`[app] screenshots` in `config.toml`.

**Download iPhone-sized screenshots only, and never look at them.** Filter by
pixel dimensions, not by opening the image: a candidate qualifies when it is
portrait and its aspect ratio is an iPhone one — height/width roughly 1.7–2.2,
e.g. 750×1334, 1170×2532, 1179×2556, 1290×2796. Skip iPad panels (4:3,
~1024×1366), landscape shots, Android/tablet captures, and web/marketing
artwork. Read the size with Pillow — the repo's existing tool dependency, so
nothing extra to install — which costs no tokens:

```bash
uv run --python 3.11 --with pillow python3 -c "
import sys; from PIL import Image
for p in sys.argv[1:]:
    w, h = Image.open(p).size; print(f'{w}x{h}  ratio {h/w:.2f}  {p}')" apps/<AppName>/images/*
```

Do **not** view, describe, judge or crop the screenshots' content — no Read,
no thumbnails, no picking the "best three". **The user picks the suitable
shots and renames them**, so keep every downloaded candidate under its
original filename, list the files for the user, and let them decide which ones
go into `[app] screenshots` (updating that list is all it takes afterwards).
Analyzing images here only burns tokens for a decision that is not yours.

Screenshots are **converted to WebP** before they are listed — the stem is
unchanged, only the extension moves to `.webp` (see [Converting Artwork to
WebP](#converting-artwork-to-webp)). List the `.webp` names you actually
wrote.

When the user supplies screenshots by hand (attached images, a folder, an
unpacked zip), **that set is the set**: copy them into
`apps/<AppName>/images/`, convert them to WebP like any other artwork, and
point each `screenshots` entry at the `.webp` file. Never rename them to
`home.png`/`detail.png`. Don't keep hunting the repo for alternatives.

`news.webp` is the one file in that folder that is generated — leave it to
`tools/render_news.py` (see [Generating News
Images](#generating-news-images)).

## README Entries

Every app appears in both `README.md` and `README_CN.md` under **Available
Apps**, in the same order. The heading (icon + name) is identical in both
files; only the one-line description differs.

**The rule is asymmetric — translate into Chinese, never into English.**
`README.md` keeps each app in its **own** language; `README_CN.md` is
**always Chinese**.

- An app whose upstream README is primarily Chinese keeps its Chinese
  one-line description in `README.md`. Do not invent an English blurb for a
  Chinese-only project: its audience reads Chinese, and its UI, docs and
  release notes stay Chinese whatever the blurb says.
- An English app gets an English blurb in `README.md` and its **Chinese
  translation** in `README_CN.md` — `README_CN.md` never carries an English
  description.

`config.toml` (`subtitle`, `description`) follows the same rule as
`README.md`: the app's own language, not the language of the page it is
written into. Those fields feed `apps.json`, and an AltStore source carries
**one** language per app — `localizedDescription` is a plain string, with no
per-locale variants — so there is no bilingual source to publish. The Chinese
text a Chinese reader sees on the site lives in `site/i18n/zh.json` instead
(see [GitHub Pages Site](#github-pages-site)).

### Three texts, one anchor

Every app carries three descriptions. They are not duplicates, and they are
not free-form either — `config.toml` `[app] subtitle` is the **anchor**:

| text | shown where | rule |
|---|---|---|
| `subtitle` | site card, "recently updated" rail, sheet header, the app list inside SideStore | one short sentence, no trailing period |
| README line | `README.md` / `README_CN.md` only | **starts with the subtitle**, then may add one concrete detail after ` — ` |
| `description` | sheet → "About" | the upstream paragraph; longer, may list requirements |

So a README line is `subtitle` plus at most one clause of real information
(a requirement, a platform, a headline feature) taken from the project's own
README — never a rewording of the same sentence. `site/i18n/zh.json` mirrors
`subtitle` and `description`, each a translation of its field, so the English
and Chinese cards read as the same sentence.

When the subtitle itself is wrong or stale, fix it in `config.toml` and
regenerate — the README line, the Chinese overlay and the site all follow it.

`news.toml`'s `tagline` is a fourth string, and deliberately not the subtitle:
it is drawn inside `images/news.webp` and must fit two full-size lines there, so
abbreviations ("Sideload apps with AltServer" for "Sideload non-notarized apps
with AltServer") are the point, not drift. See [The
tagline](#the-tagline).

⚠️ Use `align="top"` on the icon — `align="center"` renders ~7px low on
GitHub.

## Adding a New App

End-to-end procedure lives in the **add-app** skill — invoke it with
`/add-app` (it also auto-loads when you ask to add a new app). It covers
extracting fields from the project's own AltStore source (when one exists),
the folder/config/icon/news setup, tint sampling, `apps.json` generation,
merge, and README update. The reference sections below ([Icon Color Sampling
(PIL)](#icon-color-sampling-pil), [Reading an IPA's Bundle
ID](#reading-an-ipas-bundle-id), [Extracting the App Icon from an
IPA](#extracting-the-app-icon-from-an-ipa), [Generating News
Images](#generating-news-images), [Merging into
all-apps.json](#merging-into-all-appsjson)) remain authoritative for the
shared details.

## Updating an App (Repo Migration / Rename)

When an app's GitHub repo moves to a new owner/repo or the app is renamed,
the **update-app** skill handles it — invoke it with `/update-app` (it also
auto-loads when you ask to migrate or rename an existing app). Given the old
folder name and the new repo URL, it moves the folder with `git mv` (history
preserved), re-extracts every field from the new repo using the same
procedure as **add-app**, refreshes the icon/screenshots, updates
`config.toml` (repo, names, developer, URLs, tint, min OS, `[versions]`
patterns), rewrites `news.toml` including stale pinned/derived colors,
re-renders `images/news.webp`, regenerates `apps.json`, and updates the README
entry. The reference sections linked under [Adding a New
App](#adding-a-new-app) apply here too.
