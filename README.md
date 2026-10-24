# Practice document agent

Email-driven public document retrieval using Python, Playwright, Gmail IMAP/SMTP and SQLite. No LLM API key, Playwright account, Google Cloud project or OAuth configuration is required. Gmail authentication uses an app password.

## Choose how you want to test

- Email the already-running agent: no installation or password is needed. Send one matter number and one category to the address supplied by the operator. The operator must keep the program running.
- Run your own copy: follow this guide and use your own dedicated Gmail account. Repository access does not grant mailbox access.
- Test downloads without email: install the project and Chromium, then use `fetch`. Gmail setup is unnecessary for this mode.

## Verification status

The operator demonstrated on Windows with Python 3.11: a request for M12205 Other Documents was recognized, 10 files downloaded with zero reported download errors, and a reply with a ZIP was received. That establishes one end-to-end case, not all matters/categories. Metadata and manifest entries still require spot-checking. The listener's simulated tests cover inbox filtering and mail handling. This is rule-based automation, not an LLM-powered runtime.

## 1. Install uv on Windows

Open Windows Terminal or PowerShell from Start. Run:

```powershell
winget install --id=astral-sh.uv -e
```

Close and reopen PowerShell after installation, then verify:

```powershell
uv --version
```

If WinGet is unavailable, see the official uv installer instructions: https://docs.astral.sh/uv/getting-started/installation/ . Use a trusted installer rather than disabling security settings globally. You do not need to install Python separately: uv can manage it.

## 2. Download and extract the code

Sign into GitHub using an account with access to this private repository:
https://github.com/advaitgore/practice

Choose Code > Download ZIP. In File Explorer, right-click the downloaded ZIP and choose Extract All. Do not run commands inside the compressed ZIP. Open the extracted folder, descending into a second practice-main folder if necessary, until you see pyproject.toml, README.md, src and tests.

In that File Explorer window, click the address bar (or press Ctrl+L), type `powershell`, and press Enter. This opens PowerShell in the project directory. The prompt should end with the directory containing pyproject.toml. Verify:

```powershell
Get-Location
Test-Path .\pyproject.toml
```

The second command must print True. All remaining commands run from this directory. Type only the command, not a PS C:\...> prompt and not Markdown link syntax.

Alternative for Git users with authenticated private-repo access:

```powershell
git clone https://github.com/advaitgore/practice.git
cd practice
```

Git is optional if you download the ZIP.

## 3. Install Python, the project and Chromium

Use Python 3.11, the version used in the demonstrated Windows run:

```powershell
uv python install 3.11
uv sync --python 3.11
uv run playwright install chromium
uv run senpilot-agent --help
```

uv sync creates the local .venv and installs the project and dependencies. No separate pip install, virtualenv activation, global senpilot-agent installation or `uv install senpilot-agent` command is needed. Chromium downloads may take time; subsequent installs can reuse the browser cache.

Optional no-email smoke test:

```powershell
uv run senpilot-agent fetch M12205 "Other Documents"
```

A browser opens and navigates automatically. Do not click around in it during retrieval. No codegen recording or selector configuration is required for normal operation.

## 4. Prepare a dedicated Gmail account (email mode only)

Use a dedicated/burner inbox, not your main personal inbox. You need two separate email roles: the agent logs into the dedicated inbox; a different account sends test requests and receives replies.

1. Sign into the intended agent account at https://myaccount.google.com/ . Confirm the account using the profile icon, especially if several accounts are signed in.
2. Open Security & sign-in > 2-Step Verification and enable it. If Google says your existing passkey is insufficient, add another supported second step, such as an authenticator or phone number, and complete activation.
3. Open https://myaccount.google.com/apppasswords while still using the agent account.
4. Create an app password named Document Agent. Keep the generated password private. This is not your usual Google password.

App passwords require 2-Step Verification and are unavailable for some managed accounts, security-key-only configurations or Advanced Protection accounts. Google recommends Sign in with Google where supported; this implementation uses app-password IMAP/SMTP instead. Official guidance: https://support.google.com/accounts/answer/185833 .

Never share the password, authenticator QR code or verification codes; never record them in a demo. Google displays a generated app password once. If needed, revoke it and create another rather than posting it for troubleshooting.

## 5. Save the agent address

```powershell
uv run senpilot-agent setup
```

At Burner Gmail address, enter only the plain address, for example `your-agent@gmail.com` (replace this example). Do not include angle brackets, mailto: or Markdown link formatting. This saves the address and ensures Chromium is installed. The app password is not saved. If you entered the wrong account, rerun setup with the correct address.

Local settings and job state live outside the project:

```text
%USERPROFILE%\.practice-document-agent\config.json
%USERPROFILE%\.practice-document-agent\state.sqlite3
```

Do not delete state as routine troubleshooting. It prevents replaying previously handled messages. This version uses one local configuration/state directory: do not switch between multiple agent mailboxes without deliberately separating their state.

## 6. Run local tests

```powershell
uv run python -m unittest discover -s tests -v
```

There are 36 test methods in the current two test files. Local execution is the authority on their result. These tests do not connect to Gmail or the public website and do not prove every live workflow works. Stop and inspect any failures before continuing.

## 7. Test login without sending anything

```powershell
uv run senpilot-agent check-mail
```

Paste the app password at the hidden prompt and press Enter. No characters or stars appear while typing/pasting; this is expected. Success prints IMAP and SMTP login OK for the configured address. This authenticates but sends no mail. Password prompts repeat for each new command/process.

## 8. Preview inbox decisions without sending anything

```powershell
uv run senpilot-agent preview
```

Optional longer preview:

```powershell
uv run senpilot-agent preview --count 30
```

Enter the app password. Each line shows UID, sender, subject and the classification. Newsletters, Google notifications and delivery failures should show ignore. A valid request should show request: would fetch M12205 / Other Documents. Recognizable but incomplete requests show would ask for clarification. Preview does not send replies, change read flags or set the listener baseline. It can display private sender/subject information: avoid showing unrelated mail during a demo.

## 9. Test downloads locally

```powershell
uv run senpilot-agent fetch M12205 "Other Documents"
```

Other accepted categories (use one per request): Exhibits, Key Documents, Other Documents, Transcripts, Recordings. Example:

```powershell
uv run senpilot-agent fetch M12205 "Key Documents"
```

Each run writes under artifacts/<matter>_<timestamp>/ and prints its path. A successful nonempty result includes downloaded documents, manifest.csv, coverage.json and a ZIP. Open the ZIP and a few documents; compare summary fields and counts against the site. Empty categories produce no document ZIP.

The local fetch command prints reusable email text, including wording about an attachment, but does not send email. A successful fetch is not a mail-delivery test.

## 10. Start the listener and send a NEW request

```powershell
uv run senpilot-agent run
```

Enter the app password. Keep this PowerShell window open. On the first start of the UID-based listener, wait for Baseline set at message UID .... Existing inbox mail is intentionally skipped, including previous test requests. After a saved baseline exists, restarts resume from it rather than resetting every time.

Only after the baseline is set, send a new email from a DIFFERENT account to the configured agent inbox:

```text
Subject: M12205 Other Documents

Hi Agent, can you give me Other Documents files from M12205? Thanks!
```

Do not send from the agent account to itself; self-sent messages are ignored. Use a new message rather than replying to an old request for the cleanest demo.

The default polling interval is 30 seconds, plus website and download time. Logs should show request from ..., request: M12205 / Other Documents ..., downloaded ... and reply sent ... with ZIP attached. Check the sender account for the actual reply and open its attachment. A send log alone does not guarantee final inbox delivery.

Optional variants:

```powershell
uv run senpilot-agent run --interval 15
uv run senpilot-agent run --headless
uv run senpilot-agent fetch M12205 "Other Documents" --output .\artifacts
```

Headless hides the browser; headed mode is the demonstrated mode, so test headless separately before relying on it. Run only ONE listener per configured mailbox/state directory. The process handles requests sequentially.

## 11. Daily use, stop and restart

Minimize PowerShell if desired, but do not close its window/tab. Keep the laptop connected and awake; a powered-on laptop that is asleep cannot process requests. Review Windows Settings > System > Power / Power & battery > screen and sleep settings while plugged in, and lid-close behaviour if applicable. A dark screen is different from sleep. Avoid unattended updates/restarts during a promised review window. This is laptop-local software, not a hosted always-on service.

Stop by clicking PowerShell and pressing Ctrl+C. Wait for Stopped and the normal PS prompt. Restart from the project folder:

```powershell
uv run senpilot-agent run
```

Enter the app password again. With intact saved state and unchanged mailbox UID validity, newer messages still in INBOX, including ones arriving while stopped, can be processed on restart. Initial pre-baseline mail, archived/spam mail outside INBOX, skipped jobs and failed sends are not automatically recovered.

## 12. Updating after downloading a new ZIP

Stop the old listener first. You may replace/delete the old ZIP and extracted project folder, but back up artifacts you want to keep and preserve the separate user-profile settings/state directory. Download and extract the latest code, open PowerShell beside pyproject.toml, then run:

```powershell
uv sync --python 3.11
uv run playwright install chromium
uv run python -m unittest discover -s tests -v
uv run senpilot-agent preview
uv run senpilot-agent run
```

No new app password or setup is needed if your saved address and current app password remain valid. If config is missing, run setup. Re-extracting a ZIP does not automatically update any already-running old process.

## Troubleshooting

| Symptom | Check/action |
|---|---|
| uv is not recognized | Install uv; close and reopen the terminal; run uv --version. |
| No pyproject.toml found | Navigate into the extracted project root; Test-Path .\pyproject.toml must print True. |
| Chromium executable missing | Run uv run playwright install chromium in that project. |
| Gmail authentication failed | Check the configured account; use its app password, not its normal password. Check 2-Step Verification. Changing the Google password revokes existing app passwords. |
| Password appears not to paste | Hidden input shows nothing; paste once and press Enter. |
| preview command missing | You are running old code or in the wrong project folder. Download the latest main branch. |
| Request sent before first baseline | Send a fresh message after the baseline is printed. |
| Message appears in Gmail but listener ignores it | Only INBOX is scanned. Check sender, request wording, filter reason, and whether the same Message-ID was already handled. Read/unread status is irrelevant in this version. |
| No new log lines | Idle heartbeat appears every 10 polling cycles (about 5 minutes at the default interval). Incoming messages should get decision logs. |
| Sender stops getting replies | Limit is 5 replies per sender per hour; over-limit requests are skipped, not queued for later retry. Send a fresh request after the window expires. |
| Browser fails or hangs | Capture the terminal error. On top-level retrieval failure, inspect debug.png/debug.html in the newest artifacts job folder. Do not publish unrelated private data or passwords. |
| Error says element is not an input | Confirm latest scrape.py is installed; it includes the recorded-field retry/keyboard fallback. A changed site may require further inspection. |
| Reply logged but not received | Check sender inbox/spam and agent Sent/bounce messages; SMTP acceptance is not final delivery confirmation. |
| ZIP too large | Current code sends a size notice without the ZIP. This does not complete the attachment requirement for that request. No files are silently removed. |
| Need to retest after a failure | Send a new request with a new Message-ID. Do not delete the database to force retries after an uncertain send. |

## Output and limitations

ZIP contents include requested files, manifest.csv (filename, extracted document number/title/date, bytes and SHA-256), and coverage.json (counts, retrieval timestamp, policy, warnings and errors). Hashes establish byte identity, not authenticity.

Selection is first up to 10 document entries in displayed order. Multiple file buttons within one entry may produce more than 10 files; a strict ten-file cap is not currently enforced. Category counts may overlap, so their sum is not a unique-file count. Row/header parsing is layout-based and can be wrong even when a download succeeds; verify results. Other matters/categories and large recordings are not comprehensively live-tested.

The listener ignores automated/bulk/list/bounce messages and only responds to rule-recognized requests. It uses read-only IMAP and persistent UID/job tracking. Send failures are held for review, not blindly retried. Some read failures and over-limit requests are skipped; delivery is not guaranteed exactly once. Use one process, one dedicated mailbox and intact state. The code does not validate sender identity cryptographically or provide a production-grade abuse boundary.

## Demo and sharing

Prepare the environment and login before recording. Show a new request, recognition in logs, browser retrieval, received reply and ZIP/manifest. Explain the deterministic design and tested limitations. Do not expose app passwords, security QR codes, unrelated inbox mail or confidential assignment materials. Keep the code repository private and grant reviewers access explicitly; possession of a private-repo URL alone does not grant access.

At the end of evaluation, stop the listener and revoke its app password at https://myaccount.google.com/apppasswords . Back up artifacts before deleting the project.

Official setup references: https://docs.astral.sh/uv/getting-started/installation/ ; https://docs.astral.sh/uv/guides/install-python/ ; https://support.google.com/accounts/answer/185833 .
