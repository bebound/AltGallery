# AltGallery — Agent Guide

## Project Goal

Generate AltStore sources (`apps.json`) for IPA projects on GitHub.

- Generator: Python **AltGen**, invoked via `uvx altgen`

## Commits

Never ask the user whether to commit — the user commits everything
themselves. Do not run `git add`, `git commit`, or `git push` on your own
initiative, and do not end a turn with "shall I commit this?" either.

Leaving your changes in the working tree is the expected end state: report
what changed (files touched, what was regenerated) and stop there. This
applies to generated files too (`apps.json`, `all-apps.json`,
`images/news.png`) — never commit them, and never ask about committing them.

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
├── icon.png         # app icon
├── images/          # screenshots + news.png promo image
│   ├── home.png     # screenshot, listed in [app] screenshots (extension kept as-is)
│   └── news.png     # generated promo image (referenced from [news] image_url)
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
by hand; regenerate it locally with `python3 tools/make_proxy.py` when you
need to check a change.

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

The public catalog at https://bebound.github.io/AltGallery/ is a static page
built from the generated sources:

- `site/index.html`, `site/style.css`, `site/app.js` — the page. It fetches
  `all-apps.json` (served beside it) at runtime and loads icons, screenshots
  and news images from the URLs in that file. The Direct/Mirror switch
  rewrites GitHub URLs through gh-proxy.com and subscribes to the prepared
  `apps/<App>/apps-proxy.json` sources.
- `tools/build_site.py` — validates `all-apps-proxy.json` against
  `all-apps.json` (the proxy prefix is derived from the mirror), checks that
  every per-app source exists, stages the split site plus both JSON files and
  a generated `config.json` in `_site/`, and adds content hashes to the
  CSS/JS references. Stdlib only.
- `.github/workflows/pages.yml` — builds and deploys only when the update
  workflow finishes (an update run triggered by the push, including the
  bot's own commits, which never trigger `push` workflows), plus manual
  dispatch, so one push creates a single Pages deployment record. The
  repository's Pages source must be set to "GitHub Actions".

The build also writes `_site/preview.html`, with CSS, JS and the catalog
inlined, so it can be opened directly from disk:

```bash
python3 tools/build_site.py
open _site/preview.html          # single-file local preview
python3 -m http.server -d _site  # or serve the real split page
```

`_site/` is gitignored and never committed.

## Generating News Images

Each app has a shared `news.png` ("NEW UPDATE" — icon, name, tagline)
referenced by all its news entries via `[news] image_url`. Re-render every
app's image (from each app's `news.toml`: `name`, `tagline`, optional
`[colors]`) with:

```bash
./update_news.sh
```

or a single app with `.venv/bin/python3 tools/render_news.py --out
apps/<AppName>`.
Unset colors are auto-derived from `config.toml` tints and the icon's dominant
color (needs the uv venv set up once: `uv venv && uv pip install -r
requirements.txt`; Pillow is the only image dependency — no external
rasterizer). The rendered `apps/<AppName>/images/news.png` stays in the working
tree — the URL in `config.toml` `[news] image_url` already points at it. Do
not auto-commit it.

## Icon Color Sampling (PIL)

Sampling a dominant color from an icon — for a new app's `tint_color`, or the
news background derived by `render_news.py` — is already implemented in
`tools/render_news.py` → `extract_icon_color()` (it downsamples the icon
with Pillow and buckets the pixels). Just call it:

```bash
PYTHONPATH=tools .venv/bin/python3 -c \
  "from render_news import extract_icon_color; from pathlib import Path; \
   print(extract_icon_color(Path('apps/<AppName>/icon.png')))"
```

**Pillow/PIL is installed only in the project venv (`.venv/`), not in the
system Python** — any command that imports PIL (`render_news.py`,
`extract_icon_color`) must run with the venv's interpreter:
`.venv/bin/python3` (or `source .venv/bin/activate` first). The bare system
`python3` will raise `ModuleNotFoundError: No module named 'PIL'`.

When a new app lacks an official tint, use the result as `[app] tint_color`
(brand color) — but eyeball the icon first: a multi-color or pale icon may
not have an obvious single brand color, so the sample needs human
confirmation.

## Reading an IPA's Bundle ID

`[app] bundle_identifier` must be the **real** identifier — never invent one
(`com.example.*` is a placeholder). Read it from a release ipa when no AltStore
source provides it:

```bash
curl -sL "https://api.github.com/repos/<owner>/<repo>/releases/latest" \
  | jq -r '.assets[] | select(.name|endswith(".ipa")) | .browser_download_url' | head -1
tools/ipa_bundle_id.py App.ipa            # com.example.App
tools/ipa_bundle_id.py App.ipa --json     # + name, version, build, min_os_version
```

Stdlib only (`plistlib`), so the bare `python3` runs it. stdout is the
identifier alone, notes go to stderr, exit 1 when unreadable. Several
`Payload/*.app` bundles → the `CFBundlePackageType = APPL` one wins (Flutter
ships as `Runner.app`, which never matches the ipa's filename); nested
`PlugIns/`/`Watch/` bundles are ignored. Its `min_os_version` is what the
binary really needs, and it may contradict `config.toml`.

## Extracting the App Icon from an IPA

Only when the project has **no** icon to download (nothing in the repo, README,
`assets/`, or its AltStore source):

```bash
tools/ipa_icon.py App.ipa --list                     # candidates: size + file name
tools/ipa_icon.py App.ipa --out apps/<AppName>/icon.png
```

Takes the largest icon the bundle lists (`CFBundleIcons`/`CFBundleIconFiles`,
matched against `<Entry>@2x.png` / `@3x` / `~ipad` files, plus any
`*icon*.png`); nested `PlugIns/`/`Watch/` bundles are ignored, so a Watch
app's bigger icon never wins. Writes the raw square artwork — `render_news.py`
rounds it at draw time — and refuses to overwrite an icon without `--force`.
Stdlib only, bare `python3` works.

Apple's **CgBI** PNGs (BGRA, premultiplied, raw-deflate) break Pillow, so the
tool decodes them to a standard PNG that `render_news.py` can read; plain
PNGs/JPEGs are copied as-is.

⚠️ **Most ipas ship only 120x120/152x152** loose icons — the 1024px artwork sits
in `Assets.car`, unreadable here (LZFSE `bvx2`, no PNG data inside). The tool
warns below 512px: treat that as a last resort, and prefer the project's own
artwork wherever it exists.

## Screenshots

Screenshots live in `apps/<AppName>/images/` and are listed by URL in
`[app] screenshots` in `config.toml`.

When the user supplies screenshots by hand (attached images, a folder, an
unpacked zip), **use them exactly as given**: copy them into
`apps/<AppName>/images/` with their original filenames and formats (`.png`,
`.jpg`/`.jpeg`, …), and point each `screenshots` entry at the real file. Never
rename them to `home.png`/`detail.png` and never re-encode or convert the
format — AltStore loads whatever URL it is given, and the repo already ships
plenty of `.jpg`/`.jpeg` shots. The user's set is the set; don't keep hunting
the repo for alternatives.

`news.png` is the one file in that folder that is generated — leave it to
`tools/render_news.py` (see [Generating News
Images](#generating-news-images)).

## README Entries

Every app appears in both `README.md` and `README_CN.md` under **Available
Apps**, in the same order. The heading (icon + name) is identical in both
files; only the one-line description may differ.

**The description follows the language of the app's own README, not the
language of the AltGallery README it is written into.** An app whose upstream
README is primarily Chinese gets a Chinese one-line description in *both*
`README.md` and `README_CN.md`; an English upstream README gets an English
one in both. Never invent an English blurb for a Chinese-only project (or the
reverse). `config.toml` fields (`subtitle`, `description`) follow the same
rule — do not force them into English.

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
re-renders `images/news.png`, regenerates `apps.json`, and updates the README
entry. The reference sections linked under [Adding a New
App](#adding-a-new-app) apply here too.
