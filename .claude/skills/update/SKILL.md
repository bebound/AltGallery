---
name: update
description: Regenerate everything in the AltGallery repo — run ./update.sh (regenerate every apps/<AppName>/apps.json from config.toml and merge them into all-apps.json) and ./update_news.sh (re-render every app's images/news.webp from its news.toml). apps.json / all-apps.json are gitignored (committed by the workflow); leave re-rendered images/news.webp files uncommitted for the user to review. Use when the user wants to refresh / update / regenerate all app sources and news images.
---

# Update All App Sources & News Images

Refresh every generated artifact in the repo:

1. **Regenerate every app source + merge** — each `apps/<AppName>/apps.json`
   from its `config.toml`, then merged into the repo-root `all-apps.json`:
   ```bash
   ./update.sh
   ```
2. **Re-render every news image** — each `apps/<AppName>/images/news.webp`
   from its `news.toml`:
   ```bash
   ./update_news.sh
   ```
   It runs each render through `uv run tools/render_news.py`; the script's
   inline PEP 723 metadata supplies Pillow, so there is no venv to set up and
   no external rasterizer involved.

Notes:
- To verify a single app after a `config.toml` change, use the single-app form
  `./update.sh <AppName>` — it regenerates only that app and is enough for
  local verification; the full update here is for refreshing everything.
- `update.sh` reads the GitHub Releases API; if rate-limited, retry with a
  token, e.g. `GITHUB_TOKEN=$(gh auth token) uvx altgen -c config.toml`.
- `apps/<AppName>/apps.json` and `all-apps.json` are gitignored — after
  `update.sh` they won't show in `git status`; the workflow
  (`.github/workflows/update.yml`) regenerates and commits them. Only the
  re-rendered `images/news.webp` files stay in the working tree for you to
  review and commit.
- AGENTS.md rule: never leave a `config.toml` and its `apps.json` out of
  sync; `all-apps.json` is regenerated whenever any source changes.
- Proxies are not produced here: `all-apps-proxy.json` and each
  `apps/<AppName>/apps-proxy.json` come from `tools/make_proxy.py`, which the
  update workflow runs after committing. Don't run it to verify a change.
