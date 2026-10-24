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

HOME = Path.home() / ".practice-document-agent"
CONFIG = HOME / "config.json"


def _creds():
    if not CONFIG.exists():
        raise SystemExit("Run `senpilot-agent setup` first.")
    address = json.loads(CONFIG.read_text())["email"]
    pw = os.environ.get("AGENT_APP_PASSWORD") or getpass.getpass("Gmail app password (hidden, not saved): ")
    return address, pw.replace(" ", "")


def _answer(msg, args):
    """Return (body, attachment_or_None) for one request email."""
    part = msg.get_body(preferencelist=("plain",))
    text = str(msg.get("Subject", "")) + "\n" + (part.get_content() if part else "")
    try:
        matter, category = parse_request(text)
    except ValueError as exc:
        return str(exc), None
    try:
        result, archive, _ = fetch(matter, category, args.output, args.headless)
    except AgentError as exc:
        return f"Sorry, I could not complete this request: {exc}", None
    except Exception as exc:
        print("Retrieval failed:", type(exc).__name__, str(exc)[:300], file=sys.stderr)
        return ("Sorry, I could not complete this request. The site may be slow or its layout may have changed. "
                "The failure has been logged for review."), None
    return report_text(result), archive


def run(args):
    address, pw = _creds()
    HOME.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(HOME / "state.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT)")
    print("Listening. Keep this window open and the laptop awake. Ctrl+C stops it.")
    while True:
        try:
            batch = mailbox.fetch_unseen(address, pw)
        except Exception as exc:
            print("Mailbox error:", exc, file=sys.stderr)
            batch = []
        for uid, raw in batch:
            msg = email.message_from_bytes(raw, policy=default)
            key = str(msg.get("Message-ID") or hashlib.sha256(raw).hexdigest())
            skip = (msg.get("Auto-Submitted", "no").lower() != "no" or msg.get("List-ID")
                    or parseaddr(msg.get("From", ""))[1].lower() == address.lower()
                    or db.execute("SELECT 1 FROM jobs WHERE id=?", (key,)).fetchone())
            if not skip:
                db.execute("INSERT INTO jobs VALUES (?, 'processing')", (key,))
                db.commit()
                status = "needs_review"
                try:
                    try:
                        body, archive = _answer(msg, args)
                    except Exception as exc:
                        body, archive = f"Sorry, something unexpected went wrong ({type(exc).__name__}).", None
                        print("Unexpected error:", exc, file=sys.stderr)
                    try:
                        out = mailbox.build_reply(msg, address, body, archive)
                    except OverflowError:
                        size = archive.stat().st_size / 1e6
                        out = mailbox.build_reply(msg, address, body + f"\nThe ZIP is {size:.1f} MB, which is too large to attach to an email, so I have not attached it.\n")
                    mailbox.send(address, pw, out)
                    status = "sent"
                except Exception as exc:
                    print("Could not send reply:", exc, file=sys.stderr)
                db.execute("UPDATE jobs SET status=? WHERE id=?", (status, key))
                db.commit()
            try:
                mailbox.mark_seen(address, pw, uid)
            except Exception as exc:
                print("Could not mark seen:", exc, file=sys.stderr)
        time.sleep(args.interval)


def main():
    ap = argparse.ArgumentParser(prog="senpilot-agent", description="Email-driven public document retrieval")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="save burner address and install Chromium")
    sub.add_parser("check-mail", help="test Gmail IMAP/SMTP login without sending anything")
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
