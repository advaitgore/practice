# Practice document agent

Local Python tool: email it a matter number and a document type, and it fetches up to 10 public documents from the Nova Scotia Regulatory and Appeals Board database, zips them, and replies with the ZIP and a summary.

## Honest status

- Navigation follows a real recorded browser session (matter box, Search, category tab, GO GET IT, filename button, Close).
- Not yet run end to end against the live site or a real mailbox. Logic that does not need a browser has unit tests (`uv run python -m unittest discover -s tests -v`).
- Everything the site renders as text (matter header, row details) is read by position on screen. Anything that cannot be mapped is reported as missing, never guessed.
- No AI-provider key is used. Requests are parsed with strict rules and unclear requests get a clarification reply.

## Windows setup

Prerequisites: Python 3.11+ and [uv](https://docs.astral.sh/uv/). Download this repository as a ZIP (Code > Download ZIP), extract it, and open PowerShell in the folder that contains `pyproject.toml`.

```powershell
uv run senpilot-agent setup
```

Setup asks for the burner Gmail address, saves only that address under `%USERPROFILE%\.practice-document-agent`, and installs Chromium. The Gmail app password (needs 2-Step Verification on the account) is requested at runtime in a hidden prompt and is never saved. Never commit it, paste it into chat, or show it in a recording.

## Test in this order

1. Unit tests: `uv run python -m unittest discover -s tests -v`
2. Mail login only (sends nothing): `uv run senpilot-agent check-mail`
3. Browser flow, no email: `uv run senpilot-agent fetch M12205 "Other Documents"`
   Watch the browser. Output goes to `artifacts/<matter>_<timestamp>/` with the ZIP, `manifest.csv` and `coverage.json`. On failure it saves `debug.png` and `debug.html` there.
4. Full loop: `uv run senpilot-agent run`, then email the burner from another account, for example: `Can you give me Other Documents files from M12205?`

The process must stay running (laptop awake) to answer emails. Stop it with Ctrl+C.

## What the reply contains

Matter title, type, category, status, outcome, initial and final dates as shown on the site, counts for all five categories and their sum (flagged as possibly double counting), how many documents were downloaded out of those in the requested category, and the ZIP. The ZIP also holds `manifest.csv` (filename, document number, title, date, size, SHA-256) and `coverage.json` (counts, selection policy, failures, warnings).

## Known limitations

- Selection is the first 10 in the order the site displays, with no ranking.
- Documents with several files are all downloaded, so a ZIP can contain more than 10 files.
- An email over about 24 MB cannot be attached; the reply says so instead of dropping files silently.
- Row details (title, date) are best effort; `id_matches_filename` in the manifest shows whether the row read matched the downloaded file.
- Overlap between categories is flagged, not de-duplicated.
- Anyone who can email the burner address can trigger a fetch. Public data only, but do not leave it running unattended.
- Delivery is at most once per message. If sending fails the job is marked `needs_review` in the local state database and not retried automatically.

## Sharing

Keep this repository private and add reviewers as collaborators. Do not commit the assignment, screenshots, downloads, or credentials.
