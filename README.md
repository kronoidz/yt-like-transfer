# YouTube Likes Transfer

Copy your "liked" videos from one YouTube/Google account to another, using the
official [YouTube Data API v3](https://developers.google.com/youtube/v3).

The tool runs in two independent steps so each account can authorize
separately:

1. **`export`** — sign in as the **old** account and save every liked video
   (id, title, channel) to `liked.json`.
2. **`import`** — sign in as the **new** account and like each saved video,
   resuming safely where it left off.

It's designed for repeat use: because the API is quota-limited, moving a large
history takes several days, and the tool is meant to be re-run once per day.

---

## Features

- **Two-step OAuth** — the old account only needs read access; the new account
  needs the full (like/rate) scope. Each account gets its own token file.
- **Resumable** — `import` records every processed video in `liked_state.json`
  and skips them on the next run.
- **Quota-aware** — stops cleanly at the daily quota and tells you to resume
  tomorrow instead of crashing.
- **Handles real-world edge cases** — videos whose uploader disabled ratings,
  plus deleted/private videos, are skipped and recorded so they don't block
  the run.
- **`status` command** — reports progress and estimated days remaining with no
  API calls and no login.
- **`run.sh` wrapper** — auto-creates a virtualenv, installs dependencies, and
  remembers file paths so daily resume is a single command.

## Requirements

- Python 3.9+ (the wrapper creates a `.venv` automatically).
- A Google Cloud project with the **YouTube Data API v3** enabled and an OAuth
  client for a **Desktop app**.

## Setup

### 1. Create Google Cloud credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create or select a project.
2. Enable **YouTube Data API v3**
   (APIs & Services → Library → search "YouTube Data API v3" → Enable).
3. Configure the **OAuth consent screen**
   (APIs & Services → OAuth consent screen). For personal use choose
   **External**, fill in the required fields, and add yourself as a test user.
4. Create credentials:
   APIs & Services → Credentials → **Create credentials** → **OAuth client ID**
   → Application type **Desktop app**.
5. Download the JSON file.

> The "Desktop app" flow uses a local redirect (`localhost`), so there's no
> web server or public callback URL to configure.

### 2. Bootstrap the project

```sh
./run.sh setup /path/to/your/client_secret.json
```

This copies the secret into place and creates the virtualenv + installs
dependencies. It's idempotent, so you can run it again anytime.

## Usage

```sh
./run.sh export    # once, as your OLD account (opens a browser)
./run.sh import    # as your NEW account (re-run daily to resume)
./run.sh status    # check progress anytime
```

### Daily workflow

```sh
./run.sh status    # see how many are left
./run.sh import    # resume; stops on quota, re-run tomorrow
```

`import` is safe to interrupt and re-run: it resumes from `liked_state.json`
and never re-likes an already-processed video.

### Manual usage (without the wrapper)

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python3 transfer_likes.py export \
  --secrets client_secret.json \
  --token tokens/old_account.token.json \
  --out liked.json

python3 transfer_likes.py import \
  --secrets client_secret.json \
  --token tokens/new_account.token.json \
  --in liked.json \
  --state liked_state.json
```

## Quota

The YouTube Data API has a default daily quota of **10,000 units**:

| Operation            | Cost    |
| -------------------- | ------- |
| List liked videos    | 1 unit  |
| Like a video (rate)  | 50 units |

That's roughly **200 likes per day**. `import` sleeps 1 second between calls
(configurable with `--delay`) and stops when the quota is exhausted.

## Command reference

### `export`

| Option       | Default            | Description                          |
| ------------ | ------------------ | ------------------------------------ |
| `--secrets`  | (required)         | Path to `client_secret.json`         |
| `--token`    | (required)         | Token file for the OLD account       |
| `--out`      | `liked.json`       | Where to save the liked videos       |
| `--limit N`  | (no limit)         | Cap how many videos to fetch         |

### `import`

| Option       | Default            | Description                          |
| ------------ | ------------------ | ------------------------------------ |
| `--secrets`  | (required)         | Path to `client_secret.json`         |
| `--token`    | (required)         | Token file for the NEW account       |
| `--in`       | `liked.json`       | Input file from `export`             |
| `--state`    | `liked_state.json` | Resume state (auto-created)          |
| `--limit N`  | (no limit)         | Cap how many videos to like this run |
| `--delay SEC`| `1.0`              | Pause between like calls             |

### `status`

| Option    | Default            | Description              |
| --------- | ------------------ | ------------------------ |
| `--in`    | `liked.json`       | Input file               |
| `--state` | `liked_state.json` | Resume state file        |

> The `run.sh` wrapper supplies the token/state/input paths for you; you
> normally don't need to pass them by hand.

## Project layout

```
.
├── transfer_likes.py   # main script (export / import / status)
├── run.sh              # wrapper: venv + deps + file paths
├── requirements.txt    # Python dependencies
├── README.md
└── .gitignore
```

Generated at runtime (all ignored by git):

```
client_secret.json        # your OAuth client secret
tokens/                   # per-account OAuth tokens
liked.json                # exported list of liked videos
liked_state.json          # resume state
.venv/                    # virtualenv
```

## Troubleshooting

- **"Missing `client_secret.json`"** — run `./run.sh setup /path/to/file.json`.
- **"The owner of the video ... disabled ratings"** — the tool skips these
  automatically; they're recorded as processed.
- **Hit the daily quota** — normal. Re-run `./run.sh import` the next day.
- **Browser doesn't open for OAuth** — the script prints the authorization
  URL; open it manually in a logged-in browser.
- **`./run.sh` permission denied** — run `chmod +x run.sh`.

## Security & privacy

- Your OAuth `client_secret.json`, account tokens, and video data are stored
  only on your machine and are excluded from git via `.gitignore`.
- The old account is authorized with read-only access; the new account with
  the minimum scope needed to rate videos.

## Limitations

- The API has no bulk-like endpoint, so this is inherently a slow, multi-day
  process for large libraries.
- Only video IDs/titles are exported; other metadata is not needed to re-like.
