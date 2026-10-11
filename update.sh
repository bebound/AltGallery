#!/usr/bin/env bash
# AltGallery — regenerate app source(s), then merge them into the repo-root all-apps.json.
# Run: ./update.sh                       (regenerate every app source, then merge)
#      ./update.sh <AppName>             (regenerate just one app, then merge)
#      ./update.sh --skip-failures       (keep going when an app's repo fails)
# A single-app run is enough for local verification after editing a
# config.toml — the CI workflow regenerates and commits everything on push,
# so there is no need to update every app locally.
#
# --skip-failures (or SKIP_FAILURES=1 in the environment): an app whose repo
# can't be read — a 404 from a deleted or renamed repo, a rate limit — is
# reported and skipped instead of aborting the run, so every other app is
# still regenerated and merged. The skipped app keeps its previously
# generated apps.json, so it stays in all-apps.json. The script still exits 0
# (a failed step would stop the workflow before it commits) and prints which
# apps were skipped in the job summary. Use it for manual runs; the scheduled
# runs fail loudly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

skip_failures="${SKIP_FAILURES:-}"
target=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-failures)
      skip_failures=1
      ;;
    -h|--help)
      echo "Usage: ./update.sh [--skip-failures] [<AppName>]"
      exit 0
      ;;
    -*)
      echo "Error: unknown option $1" >&2
      echo "Usage: ./update.sh [--skip-failures] [<AppName>]" >&2
      exit 2
      ;;
    *)
      if [[ -n "$target" ]]; then
        echo "Error: at most one <AppName> may be given" >&2
        exit 2
      fi
      target="$1"
      ;;
  esac
  shift
done

if [[ -n "$target" && ! -f "apps/$target/config.toml" ]]; then
  echo "Error: no config.toml at apps/$target/config.toml" >&2
  echo "Usage: ./update.sh [--skip-failures] [<AppName>]" >&2
  exit 1
fi

# 1. Regenerate each apps/<AppName>/apps.json from its config.toml —
#    every app, or only the targeted one.
failed=()
for app_dir in apps/*/; do
  if [[ -f "$app_dir/config.toml" ]]; then
    name="${app_dir%/}"
    if [[ -n "$target" && "$name" != "apps/$target" ]]; then
      continue
    fi
    echo "==> Updating $name"
    if ! (cd "$app_dir" && uvx altgen -c config.toml); then
      if [[ -z "$skip_failures" ]]; then
        echo "Error: altgen failed for $name — aborting." >&2
        echo "Re-run with --skip-failures (or SKIP_FAILURES=1) to update the other apps anyway." >&2
        exit 1
      fi
      echo "!! Skipping $name — altgen failed (see its output above)." >&2
      if [[ ! -f "$app_dir/apps.json" ]]; then
        echo "   note: $name has no apps.json, so it will be missing from all-apps.json." >&2
      fi
      failed+=("$name")
    fi
  fi
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Skipped ${#failed[@]} app(s): ${failed[*]}" >&2
  if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
    echo "::warning title=update.sh::Skipped ${#failed[@]} app(s) whose repo failed: ${failed[*]}"
  fi
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo "### update.sh skipped ${#failed[@]} app(s)"
      echo
      echo "Their repo could not be read (404 / renamed / rate limit), so their existing \`apps.json\` was left as-is:"
      echo
      for name in "${failed[@]}"; do
        echo "- \`${name#apps/}\`"
      done
    } >> "$GITHUB_STEP_SUMMARY"
  fi
fi

# 2. Merge every existing source into the repo-root all-apps.json. All sources
#    are inputs whether or not they were regenerated this run, so the merged
#    file always reflects the full gallery.
apps=()
for app_dir in apps/*/; do
  if [[ -f "$app_dir/apps.json" ]]; then
    apps+=("$app_dir/apps.json")
  fi
done

if [[ ${#apps[@]} -gt 0 ]]; then
  echo "==> Merging ${#apps[@]} source(s) into all-apps.json"
  uvx altgen merge -c assets/merge.toml "${apps[@]}"
else
  echo "No app sources found — nothing to merge."
fi
