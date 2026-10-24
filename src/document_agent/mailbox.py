"""Gmail over IMAP/SMTP using an app password (standard library only)."""
import imaplib
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

IMAP_HOST, SMTP_HOST = "imap.gmail.com", "smtp.gmail.com"
MAX_EMAIL_BYTES = 24_000_000  # conservative; Gmail's limit is about 25 MB


def fetch_unseen(address, password):
    """Return [(uid, raw_bytes)] for unread inbox mail. Does not change flags."""
    found = []
    with imaplib.IMAP4_SSL(IMAP_HOST, 993) as conn:
        conn.login(address, password)
        conn.select("INBOX")
        status, data = conn.uid("search", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Inbox search failed")
        for uid in data[0].split():
            status, chunks = conn.uid("fetch", uid, "(BODY.PEEK[])")
            if status == "OK":
                raw = next((c[1] for c in chunks if isinstance(c, tuple)), None)
                if raw:
                    found.append((uid, raw))
    return found


def mark_seen(address, password, uid):
    with imaplib.IMAP4_SSL(IMAP_HOST, 993) as conn:
        conn.login(address, password)
        conn.select("INBOX")
        conn.uid("store", uid, "+FLAGS", "(\\Seen)")


def build_reply(original, address, body, attachment=None):
    to = parseaddr(original.get("Reply-To") or original.get("From", ""))[1]
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
    with imaplib.IMAP4_SSL(IMAP_HOST, 993) as conn:
        conn.login(address, password)
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context()) as smtp:
        smtp.login(address, password)
