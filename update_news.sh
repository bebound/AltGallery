#!/usr/bin/env bash
# AltGallery — regenerate every app's news.png promo image from its news.toml.
# Run: ./update_news.sh  (from anywhere; paths resolve against this script's directory)
# Each render goes through `uv run tools/render_news.py`, so uv supplies Pillow
# from the script's inline PEP 723 metadata — no venv to set up first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Regenerate each apps/<AppName>/images/news.png from apps/<AppName>/news.toml
updated=()
for app_dir in apps/*/; do
  if [[ -f "$app_dir/news.toml" ]]; then
    name="${app_dir%/}"
    echo "==> Updating $name news.png"
    uv run tools/render_news.py --out "$name"
    updated+=("$name")
  fi
done

if [[ ${#updated[@]} -eq 0 ]]; then
  echo "No news.toml found in any app folder — nothing to render." >&2
  exit 1
fi

echo "Done: ${#updated[@]} news image(s) updated (${updated[*]})."
