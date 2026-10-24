import argparse
import email
import getpass
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from email.policy import default
from email.utils import parseaddr
from pathlib import Path

from . import mailbox
from .core import AgentError, parse_request, report_text
from .scrape import fetch
from .triage import message_text, triage

HOME = Path.home() / ".practice-document-agent"
CONFIG = HOME / "config.json"
MAX_REPLIES_PER_SENDER_PER_HOUR = 5


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def _creds():
    if not CONFIG.exists():
        raise SystemExit("Run `senpilot-agent setup` first.")
    address = json.loads(CONFIG.read_text())["email"]
    pw = os.environ.get("AGENT_APP_PASSWORD") or getpass.getpass("Gmail app password (hidden, not saved): ")
    return address, pw.replace(" ", "")


def init_db(db):
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS sent (addr TEXT, ts REAL)")
    db.commit()


def _get(db, key):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return int(row[0]) if row else None


def _set(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
    db.commit()


def _answer(msg, args):
    """Return (body, attachment_or_None) for one request email."""
    text = message_text(msg)
    try:
        matter, category = parse_request(text)
    except ValueError as exc:
        log("  request incomplete; sending clarification")
        return str(exc), None
    log(f"  request: {matter} / {category}; opening the site (this takes a minute or two)")
    try:
        result, archive, _ = fetch(matter, category, args.output, args.headless)
    except AgentError as exc:
        log("  could not complete:", exc)
        return f"Sorry, I could not complete this request: {exc}", None
    except Exception as exc:
        log("  retrieval failed:", type(exc).__name__, str(exc)[:200])
        return ("Sorry, I could not complete this request. The site may be slow or its layout may have changed. "
                "The failure has been logged for review."), None
    log(f"  downloaded {len(result['downloads'])} document(s), {len(result['errors'])} error(s)")
    return report_text(result), archive


def handle(uid, raw, address, pw, db, args):
    """Handle one new inbox message. Replies only to messages that look like requests."""
    msg = email.message_from_bytes(raw, policy=default)
    sender = parseaddr(str(msg.get("From", "")))[1]
    verdict, reason = triage(msg, address)
    if verdict == "ignore":
        log(f"UID {uid}: ignored ({reason}) from {sender or '?'}")
        return
    key = str(msg.get("Message-ID") or hashlib.sha256(raw).hexdigest())
    if db.execute("SELECT 1 FROM jobs WHERE id=?", (key,)).fetchone():
        log(f"UID {uid}: already handled, skipping")
        return
    recent = db.execute("SELECT COUNT(*) FROM sent WHERE addr=? AND ts>?", (sender.lower(), time.time() - 3600)).fetchone()[0]
    if recent >= MAX_REPLIES_PER_SENDER_PER_HOUR:
        log(f"UID {uid}: not replying to {sender}; {recent} replies already sent in the last hour")
        return
    db.execute("INSERT INTO jobs VALUES (?, 'processing')", (key,))
    db.commit()
    log(f"UID {uid}: request from {sender}")
    status = "needs_review"
    try:
        try:
            body, archive = _answer(msg, args)
        except Exception as exc:
            body, archive = f"Sorry, something unexpected went wrong ({type(exc).__name__}).", None
            log("  unexpected error:", type(exc).__name__, str(exc)[:200])
        try:
            out = mailbox.build_reply(msg, address, body, archive)
        except OverflowError:
            size = archive.stat().st_size / 1e6
            out = mailbox.build_reply(msg, address, body + f"\nThe ZIP is {size:.1f} MB, which is too large to attach to an email, so I have not attached it.\n")
        mailbox.send(address, pw, out)
        db.execute("INSERT INTO sent VALUES (?, ?)", (sender.lower(), time.time()))
        status = "sent"
        log(f"  reply sent to {sender}" + (" with ZIP attached" if archive and out.is_multipart() else ""))
    except Exception as exc:
        log("  could not send reply:", type(exc).__name__, str(exc)[:200])
    db.execute("UPDATE jobs SET status=? WHERE id=?", (status, key))
    db.commit()


def run(args):
    address, pw = _creds()
    HOME.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(HOME / "state.sqlite3")
    init_db(db)
    last_uid, validity = _get(db, "last_uid"), _get(db, "validity")
    log(f"Starting for {address}. Checking every {args.interval}s. Keep this window open and the laptop awake. Ctrl+C stops it.")
    polls = 0
    while True:
        try:
            v, max_uid, new = mailbox.poll(address, pw, last_uid, validity)
        except Exception as exc:
            log("Mailbox error:", type(exc).__name__, str(exc)[:200])
            time.sleep(args.interval)
            continue
        if last_uid is None or validity != v:
            last_uid, validity = max_uid, v
            _set(db, "last_uid", last_uid)
            _set(db, "validity", validity)
            log(f"Baseline set at message UID {max_uid}. Existing mail is ignored; only new mail will be handled. "
                "If you sent a test request before this point, send it again.")
        else:
            for uid, raw in new:
                try:
                    if raw is None:
                        log(f"UID {uid}: could not be read, skipping")
                    else:
                        handle(uid, raw, address, pw, db, args)
                except Exception as exc:
                    log(f"UID {uid}: unexpected error {type(exc).__name__}: {str(exc)[:200]}")
                last_uid = uid
                _set(db, "last_uid", last_uid)
        polls += 1
        if polls % 10 == 0:
            log(f"Still listening (last message UID {last_uid}).")
        time.sleep(args.interval)


def preview(args):
    """Show what the agent would do with the newest inbox messages. Sends and changes nothing."""
    address, pw = _creds()
    for uid, raw in mailbox.recent(address, pw, args.count):
        if raw is None:
            continue
        msg = email.message_from_bytes(raw, policy=default)
        sender = parseaddr(str(msg.get("From", "")))[1]
        verdict, reason = triage(msg, address)
        detail = reason
        if verdict == "request":
            try:
                detail = "would fetch %s / %s" % parse_request(message_text(msg))
            except ValueError:
                detail = "would ask for clarification"
        print(f"UID {uid} | {sender[:38]:38} | {str(msg.get('Subject', ''))[:36]:36} | {verdict}: {detail}")


def main():
    ap = argparse.ArgumentParser(prog="senpilot-agent", description="Email-driven public document retrieval")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="save burner address and install Chromium")
    sub.add_parser("check-mail", help="test Gmail IMAP/SMTP login without sending anything")
    pv = sub.add_parser("preview", help="show what the agent would do with the newest inbox messages (sends nothing)")
    pv.add_argument("--count", type=int, default=15)
    f = sub.add_parser("fetch", help="fetch + zip locally, no email")
    f.add_argument("matter")
    f.add_argument("category")
    r = sub.add_parser("run", help="listen for requests by email")
    r.add_argument("--interval", type=int, default=30)
    for p in (f, r):
        p.add_argument("--output", default="artifacts")
        p.add_argument("--headless", action="store_true")
    args = ap.parse_args()
    if args.command == "setup":
        HOME.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps({"email": input("Burner Gmail address: ").strip()}))
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("Setup complete. The app password is asked for at runtime and never saved.")
    elif args.command == "check-mail":
        address, pw = _creds()
        mailbox.check_login(address, pw)
        print("IMAP and SMTP login OK for", address)
    elif args.command == "preview":
        preview(args)
    elif args.command == "fetch":
        matter, category = parse_request(args.matter + " " + args.category)
        result, archive, folder = fetch(matter, category, args.output, args.headless)
        print(report_text(result))
        print("Folder:", folder.resolve())
        print("ZIP:", archive.resolve() if archive else "(none created)")
    else:
        try:
            run(args)
        except KeyboardInterrupt:
            print("Stopped.")


if __name__ == "__main__":
    main()
