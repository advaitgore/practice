# Practice document agent

Local Python tool: email it a matter number and a document type, and it fetches up to 10 public documents from the Nova Scotia Regulatory and Appeals Board database, zips them, and replies with the ZIP and a summary.

## Honest status

- Website flow: ran end to end on this machine for matter M12205 (matter header, counts, 10 downloads, ZIP).
- Email flow: Gmail login works. The inbox listener was rewritten in v0.3 after it replied to old notification mail; its logic is covered by unit tests with a fake inbox, but the new version has not yet been run against the real mailbox.
- Row details and the matter header are read by position on screen. Anything that cannot be mapped is reported as missing, never guessed.
- No AI-provider key is used. Requests are parsed with strict rules and incomplete requests get a clarification reply.

## Windows setup

Prerequisites: Python 3.11+ and [uv](https://docs.astral.sh/uv/). Download this repository as a ZIP (Code > Download ZIP), extract it, and open PowerShell in the folder that contains `pyproject.toml`.

```powershell
uv run senpilot-agent setup
```

Setup asks for the burner Gmail address, saves only that address under `%USERPROFILE%\.practice-document-agent`, and installs Chromium. The Gmail app password (needs 2-Step Verification on the account) is requested at runtime in a hidden prompt and is never saved. Never commit it, paste it into chat, or show it in a recording.

## Commands

- `uv run senpilot-agent fetch M12205 "Other Documents"` fetches and zips locally, no email.
- `uv run senpilot-agent check-mail` tests the Gmail login. Sends nothing.
- `uv run senpilot-agent preview` lists the newest inbox messages and what the agent would do with each. Sends nothing, changes nothing.
- `uv run senpilot-agent run` listens for requests and replies.

## Test in this order

1. Unit tests: `uv run python -m unittest discover -s tests -v`
2. `check-mail`, then `preview`. Unrelated mail should show as `ignore`.
3. `fetch M12205 "Other Documents"`. Output goes to `artifacts/<matter>_<timestamp>/` with the ZIP, `manifest.csv` and `coverage.json`. On failure it saves `debug.png` and `debug.html` there.
4. `run`. On first start it records the newest message in the inbox and ignores everything up to that point. Then, from another account, email the burner something like: `Can you give me Other Documents files from M12205?` The window prints each decision with a timestamp.

The process must stay running (laptop awake) to answer emails. Stop it with Ctrl+C. Messages that arrive while it is stopped are handled the next time it starts.

## How the listener decides what to do

- It opens the inbox read-only and tracks the last message ID it has seen. It never marks anything read.
- It ignores no-reply and bounce senders, automated and bulk mail, mailing lists, delivery reports and its own messages.
- It only answers messages that look like requests: a matter-number-like token, or a document type together with the word "matter" or "agent". Anything else gets no reply.
- A request missing its matter number or document type gets one clarification reply. Replies go to the From address.
- At most 5 replies per sender per hour, to stop mail loops.

## What the reply contains

Matter title, type, category, status, outcome, initial and final dates as shown on the site, counts for all five categories and their sum (flagged as possibly double counting), how many documents were downloaded out of those in the requested category, and the ZIP. The ZIP also holds `manifest.csv` (filename, document number, title, date, size, SHA-256) and `coverage.json` (counts, selection policy, failures, warnings).

## Known limitations

- Selection is the first 10 in the order the site displays, with no ranking.
- Documents with several files are all downloaded, so a ZIP can contain more than 10 files.
- An email over about 24 MB cannot be attached; the reply says so instead of dropping files silently.
- Row details (title, date) are best effort; `id_matches_filename` in the manifest shows whether the row read matched the downloaded file.
- Overlap between categories is flagged, not de-duplicated.
- Mail that arrives before the very first start is not handled; send a new request after the first start.
- Delivery is at most once per message. If sending fails the job is marked `needs_review` in the local state database and not retried automatically.
- The agent only answers while this program is running.

## Sharing

Keep this repository private and add reviewers as collaborators. Do not commit the assignment, screenshots, downloads, or credentials.
