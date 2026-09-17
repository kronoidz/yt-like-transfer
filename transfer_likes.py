#!/usr/bin/env python3
"""Transfer liked YouTube videos from one account to another.

This uses the official YouTube Data API v3. It has two independent steps so
that the old account and the new account can be authorized separately:

    python3 transfer_likes.py export --secrets client_secret.json \
        --token old_account.token.json --out liked.json

    python3 transfer_likes.py import --secrets client_secret.json \
        --token new_account.token.json --in liked.json

Each account gets its own token file (created on first run via an OAuth
browser flow), but both can share the same client_secret.json from a single
Google Cloud project.

Quota note: the YouTube Data API has a default daily quota of 10,000 units.
Listing videos costs 1 unit each; rating (liking) a video costs 50 units each.
That works out to ~200 likes per day, so the import step supports resuming and
will pick up where it left off the next day if you hit the quota.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

# Reading a user's liked videos only needs read-only access. Rating (liking)
# requires the full YouTube scope.
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/youtube"

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"


def get_credentials(secrets_path: str, token_path: str, scopes: list[str]):
    """Load existing credentials or run the OAuth flow to create them."""
    # Lazy imports keep the `status`/`--help` commands dependency-free.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes)
        creds = flow.run_local_server(port=0)

    # Persist the (refresh) token so we don't have to re-auth next time.
    os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
    with open(token_path, "w") as token_file:
        token_file.write(creds.to_json())

    return creds


def build_service(creds):
    from googleapiclient.discovery import build
    return build(API_SERVICE_NAME, API_VERSION, credentials=creds, cache_discovery=False)


def list_liked_videos(youtube, limit: int | None) -> list[dict]:
    """Return every liked video as a list of {id, title, channel} dicts."""
    results: list[dict] = []
    request = youtube.videos().list(
        part="id,snippet",
        myRating="like",
        maxResults=50,
        fields="nextPageToken,items(id,snippet(title,channelTitle))",
    )

    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            results.append(
                {
                    "id": item["id"],
                    "title": item.get("snippet", {}).get("title", ""),
                    "channel": item.get("snippet", {}).get("channelTitle", ""),
                }
            )
            if limit is not None and len(results) >= limit:
                return results[:limit]
        request = youtube.videos().list_next(request, response)

    return results


def load_state(state_path: str) -> set[str]:
    """Return the set of video IDs already processed in a previous run."""
    if not os.path.exists(state_path):
        return set()
    with open(state_path, "r") as f:
        return set(json.load(f))


def save_state(state_path: str, done: set[str]) -> None:
    with open(state_path, "w") as f:
        json.dump(sorted(done), f, indent=2)


def http_error_reasons(err) -> list[str]:
    """Extract `reason` strings (e.g. 'videoRatingDisabled') from an HttpError."""
    reasons: list[str] = []
    try:
        data = json.loads(err.content.decode("utf-8"))
        for entry in data.get("error", {}).get("errors", []):
            reason = entry.get("reason")
            if reason:
                reasons.append(reason)
    except Exception:
        pass
    return reasons


def do_export(args) -> int:
    creds = get_credentials(args.secrets, args.token, [READ_SCOPE])
    youtube = build_service(creds)

    print("Fetching liked videos...")
    videos = list_liked_videos(youtube, args.limit)
    print(f"Found {len(videos)} liked video(s).")

    with open(args.out, "w") as f:
        json.dump(videos, f, indent=2)
    print(f"Saved to {args.out}")
    return 0


def do_status(args) -> int:
    """Print progress without making any API calls."""
    if not os.path.exists(args.in_):
        print(f"No input file found at {args.in_}. Run `export` first.")
        return 1

    with open(args.in_, "r") as f:
        videos = json.load(f)
    done = load_state(args.state)
    remaining = [v for v in videos if v["id"] not in done]

    print(f"Total liked videos:   {len(videos)}")
    print(f"Already processed:    {len(done)}")
    print(f"Remaining to like:    {len(remaining)}")
    if remaining:
        days = math.ceil(len(remaining) / 200)
        print(f"Est. days remaining (at ~200/day quota): {days}")
    return 0


def do_import(args) -> int:
    from googleapiclient.errors import HttpError

    creds = get_credentials(args.secrets, args.token, [WRITE_SCOPE])
    youtube = build_service(creds)

    with open(args.in_, "r") as f:
        videos = json.load(f)

    done = load_state(args.state)
    pending = [v for v in videos if v["id"] not in done]
    print(f"{len(videos)} total, {len(pending)} remaining to like.")

    if args.limit is not None:
        pending = pending[: args.limit]

    succeeded = 0
    skipped = 0
    for i, video in enumerate(pending, start=1):
        video_id = video["id"]
        title = video.get("title", "")
        try:
            youtube.videos().rate(id=video_id, rating="like").execute()
        except HttpError as err:
            reasons = http_error_reasons(err)

            if "quotaExceeded" in reasons:
                print("\nHit the daily API quota. Re-run this same command "
                      "tomorrow to resume where you left off.")
                break

            if "videoRatingDisabled" in reasons:
                note = "ratings disabled by uploader"
            elif "videoNotFound" in reasons or err.resp.status == 404:
                note = "unavailable (deleted/private)"
            else:
                # Unknown error: don't mark it done so a re-run retries it.
                print(f"\nStopped on unexpected error for '{title}': {err}")
                break

            print(f"[{i}/{len(pending)}] SKIP ({note}): {title}")
            done.add(video_id)
            save_state(args.state, done)
            skipped += 1
            continue

        done.add(video_id)
        save_state(args.state, done)
        succeeded += 1
        print(f"[{i}/{len(pending)}] liked: {title}")
        time.sleep(args.delay)

    print(f"\nDone. Liked {succeeded}, skipped {skipped} this run. "
          f"{len(done)} total processed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transfer liked YouTube videos between accounts."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- export ---
    p_export = sub.add_parser("export", help="Save liked video IDs from the OLD account.")
    p_export.add_argument("--secrets", required=True, help="Path to client_secret.json")
    p_export.add_argument("--token", required=True, help="Token file for the OLD account")
    p_export.add_argument("--out", default="liked.json", help="Output JSON file")
    p_export.add_argument("--limit", type=int, default=None, help="Max videos to fetch")
    p_export.set_defaults(func=do_export)

    # --- status ---
    p_status = sub.add_parser("status", help="Show progress (no API calls).")
    p_status.add_argument("--in", dest="in_", default="liked.json", help="Input JSON file")
    p_status.add_argument("--state", default="liked_state.json",
                          help="File tracking already-liked IDs")
    p_status.set_defaults(func=do_status)

    # --- import ---
    p_import = sub.add_parser("import", help="Like the saved videos in the NEW account.")
    p_import.add_argument("--secrets", required=True, help="Path to client_secret.json")
    p_import.add_argument("--token", required=True, help="Token file for the NEW account")
    p_import.add_argument("--in", dest="in_", default="liked.json", help="Input JSON file")
    p_import.add_argument("--state", default="liked_state.json",
                          help="File tracking already-liked IDs (for resume)")
    p_import.add_argument("--limit", type=int, default=None,
                          help="Max videos to like this run")
    p_import.add_argument("--delay", type=float, default=1.0,
                          help="Seconds to sleep between like calls (default 1)")
    p_import.set_defaults(func=do_import)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
