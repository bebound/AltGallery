#!/usr/bin/env python3
"""Read the bundle identifier out of an .ipa (iOS app archive).

An .ipa is a zip whose main app bundle sits at `Payload/<Name>.app`; the bundle
identifier is the `CFBundleIdentifier` key of that bundle's `Info.plist`
(usually a *binary* plist — plistlib reads those as well as XML ones). This
script reads it straight out of the archive.

Stdlib only (`zipfile`, `plistlib`): no external tool, no venv, no Pillow —
so the bare system `python3` runs it, unlike tools/render_news.py.

Usage:
  tools/ipa_bundle_id.py App.ipa             # prints: com.example.App
  tools/ipa_bundle_id.py App.ipa --json      # bundle id + name/version/min OS/...
  tools/ipa_bundle_id.py a.ipa b.ipa         # one "<path>\t<bundle id>" line each
  tools/ipa_bundle_id.py App.ipa --json | jq -r .bundle_id

Between several `Payload/*.app` bundles (an ipa can carry more than one) the
`CFBundlePackageType = APPL` main bundle wins, then the one whose name matches
the ipa's own filename; nested bundles (app extensions under `PlugIns/`, watch
apps) are ignored. Notes go to stderr, so stdout stays pipeable.

Exit code: 0 on success, 1 if a file is missing, is not an ipa, or carries no
readable `CFBundleIdentifier`.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import sys
import zipfile
from pathlib import Path

# The main app bundle: exactly one directory level under Payload/ — nested
# PlugIns/*.app and Watch/*.app are deliberately not matched.
APP_INFO_PLIST = re.compile(r"^Payload/(?P<name>[^/]+)\.app/Info\.plist$")


class IpaError(Exception):
    """An ipa whose bundle identifier cannot be read."""


def _normalize(text: str) -> str:
    """Lower-case and drop non-alphanumerics, for loose name comparison."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _read_candidates(path: Path) -> list[tuple[str, dict]]:
    """Every top-level `Payload/<Name>.app` bundle: (bundle name, Info.plist)."""
    candidates: list[tuple[str, dict]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.namelist():
                match = APP_INFO_PLIST.match(entry)
                if not match:
                    continue
                try:
                    with archive.open(entry) as stream:
                        info = plistlib.load(stream)
                except Exception as exc:  # unreadable/corrupt plist
                    print(f"warning: cannot parse {entry}: {exc}", file=sys.stderr)
                    continue
                if isinstance(info, dict):
                    candidates.append((match.group("name"), info))
    except zipfile.BadZipFile as exc:
        raise IpaError(f"not a zip/ipa archive: {exc}") from exc

    if not candidates:
        raise IpaError("no Payload/*.app/Info.plist found in the archive")
    return candidates


def _pick_main_app(candidates: list[tuple[str, dict]], ipa_stem: str) -> tuple[str, dict]:
    """Choose the main app bundle among several candidates."""
    apps = [c for c in candidates if str(c[1].get("CFBundlePackageType", "")).upper() == "APPL"]
    pool = apps or candidates
    if len(pool) > 1:
        stem = _normalize(ipa_stem)
        named = [c for c in pool if _normalize(c[0]) == stem]
        if named:
            pool = named
    return sorted(pool, key=lambda candidate: candidate[0])[0]


def find_main_app(path: Path) -> tuple[str, dict]:
    """The ipa's main app bundle as `(name, Info.plist)`, `name` without `.app`.

    Shared with tools/ipa_icon.py, which needs the same bundle the identifier
    was read from. Raises IpaError when the archive holds no app bundle.
    """
    candidates = _read_candidates(path)
    app_name, info = _pick_main_app(candidates, path.stem)
    if len(candidates) > 1:
        names = ", ".join(f"{name}.app" for name, _ in sorted(candidates))
        print(f"note: {len(candidates)} app bundles in Payload/: {names}", file=sys.stderr)
        print(f"note: using {app_name}.app", file=sys.stderr)
    return app_name, info


def read_ipa(path: Path) -> dict:
    """Bundle identifier and basic metadata of the ipa's main app bundle.

    Raises IpaError when the archive holds no readable bundle identifier.
    """
    if not path.is_file():
        raise IpaError("no such file")

    app_name, info = find_main_app(path)

    bundle_id = str(info.get("CFBundleIdentifier") or "").strip()
    if not bundle_id:
        raise IpaError(f"{app_name}.app/Info.plist has no CFBundleIdentifier")
    if "$(" in bundle_id:
        print(
            f"warning: bundle identifier {bundle_id!r} holds an unexpanded build "
            "variable — the Info.plist was not preprocessed",
            file=sys.stderr,
        )

    return {
        "ipa": str(path),
        "bundle_id": bundle_id,
        "app_bundle": f"{app_name}.app",
        "name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
        "version": info.get("CFBundleShortVersionString"),
        "build": info.get("CFBundleVersion"),
        "min_os_version": info.get("MinimumOSVersion"),
        "executable": info.get("CFBundleExecutable"),
        "size_bytes": path.stat().st_size,
    }


def _print_line(record: dict, path: Path) -> None:
    print(f"{path}\t{record['bundle_id']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the bundle identifier of an .ipa (one or more files).",
        epilog="With a single file and no --json, stdout is just the bundle identifier.",
    )
    parser.add_argument("ipa", nargs="+", type=Path, help="path to an .ipa file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print metadata as JSON (an object for one file, an array for several)",
    )
    args = parser.parse_args(argv)

    records: list[dict] = []
    failed = 0
    for path in args.ipa:
        try:
            record = read_ipa(path)
        except IpaError as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            failed += 1
            continue
        records.append(record)
        if not args.json and len(args.ipa) > 1:
            _print_line(record, path)

    # A single-file run prints the bare identifier (the scriptable form); with
    # several files each line is prefixed, as printed above.
    single = len(args.ipa) == 1
    if args.json and records:
        payload: object = records[0] if single else records
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif not args.json and single and records:
        print(records[0]["bundle_id"])

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
