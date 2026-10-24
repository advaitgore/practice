"""Pure logic: request parsing, page-text parsing, packaging, report text.

Nothing in this module touches a browser or the network, so it is unit tested.
"""
import csv
import hashlib
import json
import re
import statistics
import zipfile
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("Exhibits", "Key Documents", "Other Documents", "Transcripts", "Recordings")
_PATTERNS = (
    r"\bexhibits?\b",
    r"\bkey (?:documents?|docs?)\b",
    r"\bother (?:documents?|docs?)\b",
    r"\btranscripts?\b",
    r"\b(?:recordings?|audio(?: files?)?)\b",
)
MAX_DOCS = 10
SOURCE_URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"


class AgentError(Exception):
    """An error whose message is safe and useful to send back to the requester."""


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


# ---------------------------------------------------------------- requests
def parse_request(text):
    text = text.split("\nOn ")[0].split("-----Original Message-----")[0]
    text = "\n".join(x for x in text.splitlines() if not x.lstrip().startswith(">"))
    matters = set(re.findall(r"\bM[ -]?(\d{5})\b", text, re.I))
    kinds = [k for k, p in zip(CATEGORIES, _PATTERNS) if re.search(p, text, re.I)]
    if len(matters) != 1 or len(kinds) != 1:
        raise ValueError(
            "I need exactly one matter number (like M12205) and exactly one document type: "
            + ", ".join(CATEGORIES) + "."
        )
    return "M" + matters.pop(), kinds[0]


def safe_name(name):
    name = re.split(r"[/\\]", name)[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:160]
    return name or "document.bin"


def format_date(value):
    try:
        d = datetime.strptime(value, "%m/%d/%Y")
        return f"{d.strftime('%B')} {d.day}, {d.year}"
    except (TypeError, ValueError):
        return value or ""


# ------------------------------------------------------------ tab counts
def parse_tab_count(text):
    m = re.match(r"^\s*(.*?)\s*-\s*(\d+)\s*$", text or "")
    return (m.group(1), int(m.group(2))) if m else (None, None)


# ----------------------------------------------------------- header parse
_PHRASES = (
    r"matter no|status|title\s*-\s*description|type|category|date received|"
    r"decision date|date final submissions|date final|submissions|decision|outcome"
)
_LABEL_ONLY = re.compile(rf"(?:(?:{_PHRASES})\s*)+", re.I)
_LABEL_KEYS = (
    ("matter_status", r"matter\s*no"),
    ("title", r"title\s*-\s*description"),
    ("type_category", r"type"),
    ("received", r"date received"),
    ("final", r"decision date|date final|decision"),
    ("outcome", r"outcome"),
)


def parse_header(items, tab_top, tol=70):
    """Map header values to their column labels using on-screen positions.

    items: [{"text","x","y","w","h"}] for visible text. Values sit under their
    label, so each value is assigned to the label column with the closest x.
    Returns (fields, raw_lines). Missing fields are simply absent.
    """
    region = [i for i in items if i["y"] < tab_top - 2]
    raw = [norm(i["text"]) for i in sorted(region, key=lambda i: (i["y"], i["x"]))]
    labels, label_y = {}, None
    for it in region:
        t = norm(it["text"])
        if not _LABEL_ONLY.fullmatch(t):
            continue
        label_y = it["y"] if label_y is None else max(label_y, it["y"])
        for key, rx in _LABEL_KEYS:
            if key not in labels and re.match(rx, t, re.I):
                labels[key] = {"x": it["x"], "text": t}
    if len(labels) < 3 or label_y is None:
        return {}, raw
    cols = {k: [] for k in labels}
    for it in region:
        t = norm(it["text"])
        if _LABEL_ONLY.fullmatch(t) or it["y"] <= label_y + 2:
            continue
        key, best = None, tol + 1
        for k, lab in labels.items():
            d = abs(it["x"] - lab["x"])
            if d < best:
                key, best = k, d
        if key:
            cols[key].append(it)

    def texts(k):
        return [norm(i["text"]) for i in sorted(cols.get(k, []), key=lambda i: (i["y"], i["x"]))]

    out = {}
    ms = texts("matter_status")
    matter = next((t for t in ms if re.fullmatch(r"M\d{5}", t)), None)
    if matter:
        out["matter_no"] = matter
    rest = [t for t in ms if t != matter]
    if rest:
        out["status"] = " ".join(rest)
    tc = texts("type_category")
    if tc:
        out["type"] = tc[0]
    if len(tc) > 1:
        out["category"] = " ".join(tc[1:])
    for key, name in (("title", "title"), ("received", "received"), ("final", "final"), ("outcome", "outcome")):
        v = " ".join(texts(key))
        if v:
            out[name] = v
    if "final" in labels:
        out["final_label"] = labels["final"]["text"]
    return out, raw


# -------------------------------------------------------------- row parse
_SECURITY = {"public", "confidential", "private", "restricted"}


def row_meta(items, k):
    """Best-effort doc number/title/date for the k-th GO GET IT button."""
    anchors = [i for i in items if norm(i["text"]).upper() == "GO GET IT"]
    if k >= len(anchors):
        return {}
    a = anchors[k]
    cy = a["y"] + a["h"] / 2
    centers = sorted(i["y"] + i["h"] / 2 for i in anchors)
    gaps = [b - c for c, b in zip(centers, centers[1:]) if b - c > 5]
    pitch = statistics.median(gaps) if gaps else 85
    band = []
    for i in items:
        t = norm(i["text"])
        if i is a or t.upper() in ("GO GET IT", "PREVIEW"):
            continue
        if cy - pitch + 4 < i["y"] + i["h"] / 2 <= cy + 6:
            band.append((i["x"], t))
    band.sort()
    doc = next((t for _, t in band if re.fullmatch(r"\d{4,8}", t)), "")
    ext = next((t for _, t in band if re.fullmatch(r"\.[A-Za-z0-9]{1,6}", t)), "")
    date = next((t for _, t in band if re.fullmatch(r"\d{2}/\d{2}/\d{4}", t)), "")
    rest = [t for _, t in band if t not in (doc, ext, date) and t.lower() not in _SECURITY]
    title = max(rest, key=len) if rest else ""
    return {"row_doc_id": doc, "title": title, "date": date, "ext": ext}


# --------------------------------------------------------------- packaging
def _sha256(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def package(result, folder):
    """Write manifest.csv + coverage.json; return ZIP path or None if nothing downloaded."""
    folder = Path(folder)
    for d in result["downloads"]:
        d["bytes"] = Path(d["path"]).stat().st_size
        d["sha256"] = _sha256(d["path"])
    coverage = {
        "matter": result["matter"],
        "requested_category": result["category"],
        "source": SOURCE_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "header": result.get("header", {}),
        "category_counts": result["counts"],
        "category_entry_sum": sum(result["counts"].values()),
        "found_count_on_page": result.get("found_count"),
        "downloaded": len(result["downloads"]),
        "selection_policy": f"First up to {MAX_DOCS} in the order the site displays them; no ranking.",
        "overlap_note": "Category counts may overlap (a document can appear in more than one tab), so the sum is not a verified unique-file count.",
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", []),
    }
    cov_path = folder / "coverage.json"
    cov_path.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    if not result["downloads"]:
        return None
    man_path = folder / "manifest.csv"
    cols = ["position", "filename", "document_id", "title", "date", "bytes", "sha256", "id_matches_filename"]
    with man_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for n, d in enumerate(result["downloads"], 1):
            w.writerow({**d, "position": n, "document_id": d.get("row_doc_id", "")})
    target = folder / f"{result['matter']}_{result['category'].replace(' ', '_')}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for d in result["downloads"]:
            z.write(d["path"], Path(d["path"]).name)
        z.write(man_path, man_path.name)
        z.write(cov_path, cov_path.name)
    return target


# ------------------------------------------------------------------ email
def _count_phrase(counts):
    parts = [f"{v} {k}" for k, v in counts.items() if v]
    zero = [k for k, v in counts.items() if not v]
    if zero:
        parts.append("no " + " or ".join(zero))
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + ", and " + parts[-1]
    return parts[0] if parts else "no documents"


def report_text(result):
    h, c, cat = result.get("header", {}), result["counts"], result["category"]
    lines = ["Hi,", ""]
    title = h.get("title")
    if title:
        lines.append(f"{result['matter']} is about {title}.")
    else:
        lines.append(f"Here is what I found for {result['matter']}.")
    facts = [f"{label}: {h[k]}" for k, label in (("type", "Type"), ("category", "Category"), ("status", "Status"), ("outcome", "Outcome")) if h.get(k)]
    if facts:
        lines.append(" | ".join(facts))
    dates = []
    if h.get("received"):
        dates.append(f"initial filing (Date Received) on {format_date(h['received'])}")
    if h.get("final"):
        dates.append(f"{(h.get('final_label') or 'final date')} of {format_date(h['final'])}")
    if dates:
        lines.append("The matter had " + " and a ".join(dates) + ".")
    if not h:
        lines.append("I could not map the matter header fields reliably, so none are reported.")
    lines += ["", f"I found {_count_phrase(c)}. That is {sum(c.values())} files listed across the five categories; "
              "some documents may appear in more than one category, so this may double-count.", ""]
    got, total = len(result["downloads"]), c.get(cat, 0)
    if total == 0:
        lines.append(f"This matter has no {cat}, so there is nothing to attach.")
    elif got:
        lines.append(f"I downloaded {got} out of the {total} {cat} (the first {MAX_DOCS} in the order the site shows them) "
                     "and am attaching them as a ZIP, along with manifest.csv (checksums) and coverage.json.")
    else:
        lines.append(f"I could not download any of the {total} {cat}.")
    if result["errors"]:
        lines.append(f"{len(result['errors'])} document(s) failed: " + "; ".join(f"#{e['index']} {e['error']}" for e in result["errors"][:5]))
    for w in result.get("warnings", []):
        lines.append("Note: " + w)
    return "\n".join(lines) + "\n"
