"""Decide whether an incoming email is a document request. Pure functions, no network."""
import re
from email.utils import parseaddr

from .core import _PATTERNS

_AUTOMATED_SENDER = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer[-_.]?daemon|postmaster|bounce|notifications?|newsletter|alerts?)",
    re.I,
)
_LOOSE_MATTER = re.compile(r"\bM[ -]?\d{3,6}\b", re.I)
_CATEGORY = re.compile("|".join(_PATTERNS), re.I)
_ADDRESSING = re.compile(r"\b(matter|agent)\b", re.I)


def strip_quotes(text):
    text = text.split("\nOn ")[0].split("-----Original Message-----")[0]
    return "\n".join(x for x in text.splitlines() if not x.lstrip().startswith(">"))


def message_text(msg):
    """Subject plus the plain-text body (HTML tags stripped if there is no plain part)."""
    body = ""
    try:
        part = msg.get_body(preferencelist=("plain",))
        if part is not None:
            body = part.get_content()
        else:
            html = msg.get_body(preferencelist=("html",))
            if html is not None:
                body = re.sub(r"<[^>]+>", " ", html.get_content())
    except Exception:
        body = ""
    return str(msg.get("Subject", "")) + "\n" + body


def triage(msg, own_address):
    """Return ("ignore", reason) or ("request", "").

    "request" means the message is addressed to the agent. It may still be
    incomplete, in which case the caller sends a clarification.
    """
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    if not sender or "@" not in sender:
        return "ignore", "no valid sender"
    if sender == own_address.lower():
        return "ignore", "sent by this mailbox"
    if _AUTOMATED_SENDER.search(sender.split("@")[0]):
        return "ignore", "automated sender"
    if str(msg.get("Auto-Submitted", "no")).strip().lower() != "no":
        return "ignore", "auto-submitted"
    if str(msg.get("Precedence", "")).strip().lower() in {"bulk", "list", "junk"}:
        return "ignore", "bulk mail"
    if msg.get("List-Id") or msg.get("List-Unsubscribe"):
        return "ignore", "mailing list"
    if msg.get_content_type() == "multipart/report":
        return "ignore", "delivery report"
    text = strip_quotes(message_text(msg))
    if _LOOSE_MATTER.search(text):
        return "request", ""
    if _CATEGORY.search(text) and _ADDRESSING.search(text):
        return "request", ""
    return "ignore", "not a document request"
