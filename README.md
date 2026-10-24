# Practice document agent

## Status
Draft implementation. Browser selectors are not live-site verified. Gmail delivery and Windows installation require local testing. Do not present this as an end-to-end verified submission. No AI-provider API key is required.

## Windows setup
Install Python 3.11+ and uv. Download this private repository using GitHub Code > Download ZIP and extract it, or clone it with authenticated Git. Open PowerShell in the extracted project directory.

```powershell
uv run senpilot-agent setup
uv run python -m unittest discover -s tests -v
```

Setup downloads Chromium and stores only your burner email under your user profile in .practice-document-agent/config.json. Run prompts secretly for a Gmail app password, not your normal password. App passwords require an eligible account with 2-Step Verification. Do not paste secrets into chat, commits or demos. AGENT_APP_PASSWORD is an optional environment variable.

## Required live-browser inspection
```powershell
uv run playwright codegen https://uarb.novascotia.ca/fmi/webd/UARB15
Copy-Item selectors.example.json selectors.local.json
```
Replace every placeholder in selectors.local.json with an inspected CSS/Playwright selector. The search selector must uniquely identify the direct-matter Search button, not the advanced-search button. Header must select matter metadata, not the entire page. Rows must select individual document rows. Filename must select the final confirmation control after GO GET IT. Screenshots alone cannot supply these selectors.

```powershell
uv run senpilot-agent fetch M12205 "Other Documents" --selectors selectors.local.json
uv run senpilot-agent run --selectors selectors.local.json
```

First verify a local fetch ZIP. Then start run and email the burner from a different account. Keep the laptop awake and the process running. Files are saved under artifacts. Debug screenshots/HTML may contain matter metadata; keep them local.

## Implemented
Strict matter/category parser, quoted-line filtering, all-five-category count validation, deterministic first-up-to-10 selection, empty-category handling, unique file names, ZIP, SHA-256 manifest, coverage JSON, MIME size check, threaded SMTP replies, clarification for invalid requests, SQLite job state. IMAP reads do not mark messages as read.

## Known limitations
Live selectors must be supplied before fetch can succeed. Scrolling/virtualized rows, popup downloads, date normalization and modal recovery are not implemented. The adapter stops if too few rows are loaded; after a download error it stops rather than risk clicking the wrong document. Save List export parsing and cross-category deduplication are not implemented. Category-entry sum is explicitly not a unique-file count.

Oversized serialized emails (over conservative 24 MB budget) are marked needs_review locally; no documents are silently dropped and no link substitutes for the requested ZIP. Scraping failures likewise require local review. Automated success is not reported on failure.

SQLite prevents routine duplicate processing but exactly-once SMTP delivery is not guaranteed. Interrupted processing remains held for review to avoid blind resending. Run only one instance per mailbox. For retesting, send a new message with a new Message-ID. Do not delete state blindly after an uncertain send.

## Sharing
Keep this repository private. Do not commit the assignment, screenshots, downloaded files, Gmail credentials or tokens. Reviewer access needs their GitHub username and a separate invitation. Hashes identify bytes; they do not prove source authenticity.
