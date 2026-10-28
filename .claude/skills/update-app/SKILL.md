---
name: update-app
description: Handle a repo migration or app rename for an app already in AltGallery. The user supplies the existing app folder name and the new repo URL; Claude moves the folder with git mv (preserving history), re-extracts the project metadata from the new repo (AltStore source / README / release ipa — description, subtitle, bundle id, developer, icon, screenshots), updates config.toml (repo, URLs, tint, min_os_version, asset_pattern), rewrites news.toml (name, tagline, stale pinned and derived colors), re-renders images/news.png, regenerates apps.json, and updates the README entry. Use when an app's GitHub repo moves to a new owner/repo, the app is renamed, or both.
---

# Updating an App: Repo Migration or Rename

An app already in the gallery changed its GitHub repo (new owner, new repo
name, or both) and possibly its display name. The goal is to migrate the
existing folder in git — keeping its history — and then refresh every piece of
metadata from the **new** repo, exactly as `/add-app` would extract it for a
new app.

This skill only covers what differs from `/add-app`; the shared details
(extracting fields from an AltStore source, reading a bundle id / icon from an
ipa, tint sampling, news rendering) are in that skill and in AGENTS.md.

## Inputs

Ask for whichever is missing before touching the tree:

- **Old app name** — the existing folder under `apps/` (e.g. `PiliPlus`),
  case-sensitive.
- **New repo URL** — `https://github.com/<owner>/<repo>` (a bare `owner/repo`
  is fine).

Then confirm the folder exists:

```bash
ls -d apps/<OldName>
```

If it is not there, list `apps/` and match case-insensitively — never guess
which app was meant.

## Procedure

1. **Resolve the new name**

   Read the new repo's metadata first:

   ```bash
   curl -sL "https://api.github.com/repos/<owner>/<repo>" \
     | jq '{full_name, default_branch, description, homepage, archived}'
   ```

   Derive the display name, in this order:
   1. `apps[0].name` from the new repo's own AltStore source (locate it the
      same way as `/add-app` step 2 — README JSON links, `altstore/` folder,
      or a dedicated branch);
   2. the app name used in the new README / latest release title;
   3. the repo name.

   The **folder name** normally mirrors the new repo name or the display
   name, matching the repo's casing; the two may differ — existing examples:
   folder `Venera-Next` → display `VeneraNext`, folder `Suwayomi-Tsumiru` →
   display `Tsumiru`, folder `AirCard` → display `AirCard-iOS`. Reuse the old
   folder name when the app was not renamed (repo migration only).

   If the new display name is ambiguous (repo name and README/source disagree,
   or the repo name is not a plausible app name), ask the user which name to
   use before moving anything.

2. **Move the folder in git**

   ```bash
   git mv apps/<OldName> apps/<NewName>
   ```

   Use `git mv`, never `mv` + `git add`: it keeps rename detection and the
   tracked `apps.json` inside the folder moves with it. The rename is staged;
   **do not commit** (AGENTS.md).

   - Name unchanged? Skip the move and continue with step 3.
   - Case-only rename on macOS (case-insensitive filesystem) needs two steps:
     ```bash
     git mv apps/Foo apps/Foo-rename && git mv apps/Foo-rename apps/foo
     ```
   - If a screenshot or image file name contains the old app name, rename it
     too and update its `[app] screenshots` entry.

3. **Re-extract the project metadata from the new repo**

   Follow `/add-app` steps 2–3 against the **new** owner/repo, not the old
   URL (GitHub redirects old repo URLs, but the redirect carries stale asset
   names and owner data):

   - Find the project's own AltStore source and map it to the config fields
     (name, bundleIdentifier, developerName, subtitle, localizedDescription,
     iconURL, tintColor, screenshots, minOSVersion, downloadURL).
   - No source: derive description/subtitle from the new README, and get
     `bundle_identifier` / `min_os_version` from a release ipa with
     `tools/ipa_bundle_id.py`. Never invent an identifier.
   - **Re-verify the bundle identifier.** A rename or ownership change can
     ship a different identifier; silently carrying the old one over makes
     the gallery install a different app (or fail). If the new repo offers no
     way to verify it, keep the existing value and say in the report that it
     was not re-verified.
   - **Icon:** prefer the new repo's artwork (repo, README, `assets/`, or its
     AltStore source). If the new repo has none, keep the existing
     `icon.png` — it is still the app's artwork — rather than falling back to
     the small loose ipa icon; only use `tools/ipa_icon.py` when the existing
     icon is missing or obviously stale.
   - **Screenshots:** download the new repo's screenshots when it has them;
     otherwise keep the existing local screenshots (still valid, already
     hosted here). If there are none at all, warn at the end exactly as
     `/add-app` step 10 requires.
   - Copy assets into `apps/<NewName>/` and reference them through the
     `bebound/AltGallery` raw URLs — never point `config.toml` at the source's
     remote URLs.

4. **Update `config.toml`**

   Re-read the reference config (`apps/PiliPlus/config.toml`) so the section
   order and shared wording stay current, then change the values **in place**
   — this is an existing app, do not rebuild the file from the template.
   Everything that names the app, the repo, or the folder changes:

   | Location | New value |
   |---|---|
   | header comment | new display name / one-line description |
   | `[github] repo` | `<new-owner>/<repo>` |
   | `[source] name`, `subtitle`, `description` | new display name; keep the shared "… AltStore source by AltGallery & AltGen" wording |
   | `[source] website` | new repo URL |
   | `[source] icon_url` | `.../apps/<NewName>/icon.png` |
   | `[source] tint_color` | new brand color when it changed (source `tintColor`, normalized to `#RRGGBB`) |
   | `[app] name` | new display name |
   | `[app] bundle_identifier` | re-verified value (step 3) |
   | `[app] developer_name` | new owner (or the source's `developerName`) |
   | `[app] subtitle`, `description` | refreshed from the new repo |
   | `[app] icon_url`, `screenshots` | `.../apps/<NewName>/...` |
   | `[app] tint_color`, `min_os_version` | new values when the icon / ipa changed |
   | `[versions]` | re-derive from the new repo's latest release (step 5) |
   | `[news] image_url` | `.../apps/<NewName>/images/news.png` |

   `[output] path = "apps.json"` never changes.

   ⚠️ **The folder rename does not rewrite URLs** — every `apps/<OldName>/`
   segment in `[source] icon_url`, `[app] icon_url`, `screenshots`, and
   `[news] image_url` must be replaced by hand.

   ⚠️ **Release naming often differs in the new repo.** Check the latest
   release's asset names and re-derive `[versions]`:
   - `asset_pattern` is a **regex**, not a glob — the exact new ipa filename
     (e.g. `"^NewName\\.ipa$"`) or `".*\\.ipa$"` for any ipa;
   - `strip_v_prefix`, `version_pattern`, `build_version_pattern`, and
     `include_prereleases` only when the new tags/assets need them — drop
     stale patterns that encode the old repo's scheme;
   - update any comment that names old assets or tag formats.

5. **Rewrite `news.toml`, including stale colors**

   - Header comment: new `--out apps/<NewName>` path.
   - `name` → new display name; `tagline` → a short version of the new
     subtitle/description.
   - **Colors:** pinned `[colors]` overrides were chosen for the old icon and
     brand. On a migration the icon or brand color may have changed, so
     re-check every pin:
     - print the effective palette (next snippet);
     - keep a pin that still fits the new artwork/brand;
     - update a pin derived from the old icon (e.g. a tint sampled from the
       old icon's dominant color), and its inline comment explaining why it
       was pinned;
     - delete a pin whose reason no longer exists, so the auto-derivation
       takes over again.

   The commented "current result" values in the `[colors]` block are shown to
   whoever edits the file next — refresh them to the newly effective values.
   Do not leave a stale palette behind.

   ⚠️ `render_news.py` needs Pillow, which lives only in the project venv —
   always use `.venv/bin/python3`, never the bare `python3`. Remember the
   AGENTS.md caveat about sampling a dark/monochrome icon.

   Print the effective palette for the new icon (run this block as-is — it
   stays at column 0 so the heredoc delimiter works):

```bash
PYTHONPATH=tools .venv/bin/python3 - <<'PY'
from pathlib import Path
from render_news import (load_configs, extract_icon_color,
                         derive_light_background, derive_background,
                         derive_bg_stops, auto_text_color,
                         derive_tagline_color)

out = Path("apps/<NewName>")
news, cfg = load_configs(out)
colors = news.get("colors", {}) or {}
app_tint = (cfg.get("app") or {}).get("tint_color")
src_tint = (cfg.get("source") or {}).get("tint_color")

tint = colors.get("tint") or app_tint or "#73B480"
tint_alt = colors.get("tint_alt") or src_tint or tint
bg = colors.get("background")
if bg is None:
    icon_color = extract_icon_color(out / "icon.png")
    bg = derive_light_background(icon_color) if icon_color else derive_background(tint)
mid, dark = derive_bg_stops(bg)
print("tint          =", tint.upper())
print("tint_alt      =", tint_alt.upper())
print("background    =", bg.upper())
print("bg_mid        =", (colors.get("bg_mid") or mid).upper())
print("bg_dark       =", (colors.get("bg_dark") or dark).upper())
print("text_color    =", (colors.get("text_color") or auto_text_color(bg)).upper())
print("tagline_color =", (colors.get("tagline_color") or derive_tagline_color(bg)).upper())
PY
```

6. **Render the new promo image** (AGENTS.md → [Generating News
   Images](../AGENTS.md#generating-news-images)):

   ```bash
   ./.venv/bin/python tools/render_news.py --out apps/<NewName>
   ```

   Writes `apps/<NewName>/images/news.png` into the working tree — do not
   auto-commit it.

7. **Regenerate the source** (never hand-edit `apps.json`):

   ```bash
   ./update.sh <NewName>
   ```

   This regenerates only this app's `apps.json` and re-merges
   `all-apps.json`. Both are gitignored and regenerated/committed by the CI
   workflow (`.github/workflows/update.yml`) — leave the modified
   `all-apps.json` in the working tree, never commit it. If altgen is
   rate-limited or the repo is private, use
   `GITHUB_TOKEN=$(gh auth token) uvx altgen -c config.toml` in the folder.

8. **Update the README entry**

   Replace the app's `###` heading and description line in **Available Apps**:

   ```html
   ### <a href="https://github.com/<new-owner>/<repo>"><img src="https://raw.githubusercontent.com/bebound/AltGallery/master/apps/<NewName>/icon.png" alt="<display name> icon" width="24" align="top"> <display name></a>
   One-line description.
   ```

   - Keep `align="top"` on the icon (`align="center"` renders ~7px low).
   - The heading text is the **display name**, which may differ from the
     folder name — do not blindly copy the folder.
   - Move the entry if the new display name changes its alphabetical
     position in the list.
   - Refresh the one-line description when the project's description changed.

9. **Sweep for stale references**

   ```bash
   grep -rn "<OldName>" --exclude-dir=.git --exclude=apps.json --exclude=all-apps.json .
   grep -rni "<oldname>" --exclude-dir=.git --exclude=apps.json --exclude=all-apps.json .
   ```

   Every remaining hit must be intentional (e.g. a comment that explains the
   old name). Check `git status` shows the folder as a rename (`R`), not a
   delete + untracked add.

10. **Report** — summarize: old → new folder and display name, new repo,
    whether the bundle identifier changed (⚠️ a new identifier is a new app
    for AltStore — existing installs will not upgrade in place), tint/palette
    changes, icon source, screenshots refreshed or kept, any old-name
    references left on purpose, and whether screenshots are missing. Then
    stop — do **not** commit and do **not** ask about committing.

## Checklist

- [ ] inputs confirmed; old folder matched case-sensitively
- [ ] new display name resolved from the new repo's source/README; ambiguity asked about
- [ ] folder moved with `git mv` (two-step for case-only renames), history preserved
- [ ] metadata re-extracted from the **new** repo, not the old redirect
- [ ] bundle identifier re-verified (or explicitly reported as unverified)
- [ ] icon refreshed from the new repo when available; existing icon kept when not
- [ ] new screenshots downloaded when available; existing kept otherwise; missing screenshots warned about
- [ ] `config.toml`: repo, source/app names, developer, URLs, tint, min OS and `[versions]` patterns all updated; every `apps/<OldName>/` URL gone
- [ ] `news.toml`: name, tagline, header path updated; pinned colors re-checked against the new icon/brand; commented "current result" palette refreshed
- [ ] `images/news.png` re-rendered with the new name
- [ ] `apps.json` regenerated via `./update.sh <NewName>`, never hand-edited, not committed
- [ ] `all-apps.json` left modified in the working tree, not committed
- [ ] README entry updated (href, icon `align="top"`, display name) and re-sorted if needed
- [ ] stale-reference grep clean or hits explained
