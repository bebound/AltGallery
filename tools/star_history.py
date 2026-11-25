#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Report how many GitHub stars this project gained on each of the last 30 days.

GitHub exposes no star-history API, but the stargazers endpoint can return
each star's timestamp (`Accept: application/vnd.github.star+json`), so the
daily totals are reconstructed from that list. It requires authentication —
anonymous calls to /stargazers return 401 — and the timestamped form is what
the token buys.

The listing is chronological (oldest first), and the Link header's `last`
page gives the total, so the script only fetches the tail: it binary-searches
for the first page that reaches back into the window, then reads forward from
there. Pages already fetched by the search are reused, and the remaining
window pages are fetched concurrently, since each request costs a fresh TLS
handshake. An authenticated token gets 5000 requests/hour instead of 60.

Auth: `--token` > `GITHUB_TOKEN` env > the `gh` CLI's stored token, in that
order. Stdlib only — the inline metadata declares no dependencies.

Usage (from the repo root; uv reads the inline PEP 723 metadata):
  uv run tools/star_history.py                     # last 30 days, one row per day
  uv run tools/star_history.py --days 14
  uv run tools/star_history.py --repo owner/name   # default: this repo's origin
  uv run tools/star_history.py --json              # machine-readable output
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.github.com"
STAR_JSON = "application/vnd.github.star+json"
LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')
LINK_LAST = re.compile(r'<([^>]+)>;\s*rel="last"')
PER_PAGE = 100


class StarHistoryError(RuntimeError):
    pass


def detect_repo() -> str:
    """owner/repo from the git remote named origin."""
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise StarHistoryError("no `origin` remote; pass --repo owner/name")
    # git@github.com:owner/repo.git  or  https://github.com/owner/repo.git
    match = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", remote)
    if not match:
        raise StarHistoryError(f"cannot parse a GitHub repo from origin URL {remote!r}; pass --repo")
    return f"{match.group(1)}/{match.group(2)}"


def resolve_token(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env:
        return env
    gh = shutil.which("gh")
    if gh:
        try:
            token = subprocess.run(
                [gh, "auth", "token"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            if token:
                return token
        except subprocess.CalledProcessError:
            pass
    raise StarHistoryError(
        "no GitHub token: pass --token, set GITHUB_TOKEN, or run `gh auth login` "
        "(the timestamped stargazers list requires authentication)"
    )


def api_get(url: str, token: str) -> tuple[list[dict], dict[str, str]]:
    request = urllib.request.Request(url, headers={
        "Accept": STAR_JSON,
        "Authorization": f"Bearer {token}",
        "User-Agent": "AltGallery-star-history",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
            headers = dict(response.headers)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        hint = " (token missing the `public_repo`/`repo` scope?)" if error.code in (401, 403) else ""
        raise StarHistoryError(f"GitHub API {error.code} for {url}{hint}: {detail}")
    except urllib.error.URLError as error:
        raise StarHistoryError(f"cannot reach GitHub: {error.reason}")
    return body, headers


def page_url(repo: str, page: int) -> str:
    return f"{API}/repos/{repo}/stargazers?per_page={PER_PAGE}&page={page}"


def fetch_page(repo: str, page: int, token: str) -> tuple[list[datetime], int]:
    """One page of star timestamps (oldest first) plus the total page count."""
    stars, headers = api_get(page_url(repo, page), token)
    stamps = [datetime.fromisoformat(s["starred_at"].replace("Z", "+00:00")) for s in stars]
    last = LINK_LAST.search(headers.get("Link", ""))
    # `[?&]page=` — a bare `page=(\d+)` would match the `per_page=100` first.
    total_pages = int(re.search(r"[?&]page=(\d+)", last.group(1)).group(1)) if last else page
    return stamps, total_pages


def daily_counts(repo: str, days: int, token: str) -> list[tuple[date, int]]:
    """(day, stars gained that day) for the window ending today, oldest first.

    Days are UTC, matching the timestamps GitHub returns.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    window_start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    counts = {start + timedelta(days=i): 0 for i in range(days)}

    cache: dict[int, list[datetime]] = {}

    def stamps_of(page: int) -> list[datetime]:
        """One page's star timestamps, fetched at most once."""
        if page not in cache:
            cache[page] = fetch_page(repo, page, token)[0]
        return cache[page]

    first_stamps, total_pages = fetch_page(repo, 1, token)
    cache[1] = first_stamps
    if not first_stamps:
        return sorted(counts.items())

    # The list is chronological, so the window is a suffix of it: binary-search
    # for the first page that still holds a star inside the window, then read
    # forward. A page's last star is its newest.
    low, high = 1, total_pages
    while low < high:
        mid = (low + high) // 2
        page_stamps = stamps_of(mid)
        if page_stamps and page_stamps[-1] < window_start:
            low = mid + 1          # this page and every earlier one predate the window
        else:
            high = mid
    first_page = low

    # The remaining pages are independent, and a request costs a TLS handshake,
    # so fetch them in parallel; `stamps_of` keeps a page from being fetched twice.
    rest = [page for page in range(first_page, total_pages + 1) if page not in cache]
    with ThreadPoolExecutor(max_workers=min(6, len(rest) or 1)) as pool:
        list(pool.map(stamps_of, rest))

    for page in range(first_page, total_pages + 1):
        for stamp in cache[page]:
            if stamp.date() in counts:
                counts[stamp.date()] += 1

    return sorted(counts.items())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily GitHub star growth for this project over the last N days (UTC days).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Auth: --token > GITHUB_TOKEN / GH_TOKEN > `gh auth token`.",
    )
    parser.add_argument("--repo", help="owner/name (default: parsed from the origin remote)")
    parser.add_argument("--days", type=int, default=30, help="window length in days (default: 30)")
    parser.add_argument("--token", help="GitHub token (default: env or gh CLI)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--no-chart", action="store_true", help="omit the bar chart")
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be at least 1")

    try:
        repo = args.repo or detect_repo()
        token = resolve_token(args.token)
        rows = daily_counts(repo, args.days, token)
    except StarHistoryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(
            {"repo": repo, "days": [
                {"date": d.isoformat(), "stars": n} for d, n in rows
            ], "total": sum(n for _, n in rows)},
            sys.stdout, indent=2,
        )
        print()
        return 0

    total = sum(n for _, n in rows)
    peak = max((n for _, n in rows), default=0)
    print(f"{repo} — stars gained per day, last {args.days} days (UTC)")
    print(f"{rows[0][0]} … {rows[-1][0]}  total +{total}  avg {total / len(rows):.2f}/day")
    print()
    for day, count in rows:
        bar = ""
        if not args.no_chart and peak and count:
            bar = "  " + "█" * max(1, round(count / peak * 40))
        print(f"{day.isoformat()}  {count:4d}{bar}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
