"""Gmail over IMAP/SMTP using an app password (standard library only).

The inbox is opened read-only: this module never changes message flags.
"""
import imaplib
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

IMAP_HOST, SMTP_HOST = "imap.gmail.com", "smtp.gmail.com"
MAX_EMAIL_BYTES = 24_000_000  # conservative; Gmail's limit is about 25 MB


def select_new(uids, last_uid):
    return sorted(u for u in uids if u > last_uid)


def _open(address, password):
    conn = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    conn.login(address, password)
    status, _ = conn.select("INBOX", readonly=True)
    if status != "OK":
        raise RuntimeError("Could not open INBOX")
    return conn


def _validity(conn):
    _, data = conn.response("UIDVALIDITY")
    return int(data[0]) if data and data[0] else 0


def _all_uids(conn):
    status, data = conn.uid("search", None, "ALL")
    if status != "OK":
        raise RuntimeError("Inbox search failed")
    return [int(x) for x in data[0].split()]


def _fetch_raw(conn, uid):
    status, chunks = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
    if status != "OK":
        return None
    return next((c[1] for c in chunks if isinstance(c, tuple)), None)


def _close(conn):
    try:
        conn.logout()
    except Exception:
        pass


def poll(address, password, last_uid, validity):
    """Read-only check. Returns (validity_now, max_uid, [(uid, raw_or_None)]).

    If there is no baseline yet (last_uid is None) or the mailbox's UIDVALIDITY
    changed, no messages are returned; the caller should set a new baseline.
    """
    conn = _open(address, password)
    try:
        v = _validity(conn)
        uids = _all_uids(conn)
        max_uid = max(uids, default=0)
        if last_uid is None or validity != v:
            return v, max_uid, []
        return v, max_uid, [(u, _fetch_raw(conn, u)) for u in select_new(uids, last_uid)]
    finally:
        _close(conn)


def recent(address, password, count=15):
    """Return the newest `count` messages as [(uid, raw)], oldest first."""
    conn = _open(address, password)
    try:
        return [(u, _fetch_raw(conn, u)) for u in sorted(_all_uids(conn))[-count:]]
    finally:
        _close(conn)


def build_reply(original, address, body, attachment=None):
    to = parseaddr(str(original.get("From", "")))[1]
    if not to or to.lower() == address.lower():
        raise ValueError("No valid reply address")
    msg = EmailMessage()
    msg["From"], msg["To"] = address, to
    subject = str(original.get("Subject", "Document request"))
    msg["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
    mid = original.get("Message-ID")
    if mid:
        msg["In-Reply-To"] = str(mid)
        msg["References"] = (str(original.get("References", "")) + " " + str(mid)).strip()
    msg["Auto-Submitted"] = "auto-replied"
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="zip", filename=attachment.name)
    if len(msg.as_bytes()) > MAX_EMAIL_BYTES:
        raise OverflowError("attachment too large for email")
    return msg


def send(address, password, msg):
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context()) as smtp:
        smtp.login(address, password)
        smtp.send_message(msg)


def check_login(address, password):
    conn = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    try:
        conn.login(address, password)
    finally:
        _close(conn)
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context()) as smtp:
        smtp.login(address, password)
