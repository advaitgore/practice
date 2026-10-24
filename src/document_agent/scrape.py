"""Playwright navigation for the UARB public documents database.

Interactions below mirror a real recorded session (matter box, the 5th
"Search" button, tab buttons, GO GET IT, filename button, Close). Page *text*
parsing lives in core.py. Anything not seen in the recording is best-effort and
is reported as a warning rather than guessed.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from .core import (CATEGORIES, MAX_DOCS, SOURCE_URL, AgentError, package,
                   parse_header, parse_tab_count, row_meta, safe_name)

INPUT_CANDIDATES = ("#b0p0o254i0i0r1 > .inner_border > .text", 'input[placeholder*="M01234"]')
SEARCH_INDEXES = (4, 3, 5)  # 4 was recorded; others are fallbacks on a fresh page load
VIEWPORT = {"width": 1600, "height": 1000}
FILE_BUTTON = re.compile(r"^\S.*\.[A-Za-z0-9]{2,5}$")
CURTAIN = ".v-window-modalitycurtain"
GO_GET_IT = re.compile(r"GO GET IT", re.I)

JS_ITEMS = r"""() => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    let t = '';
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent + ' ';
    t = t.replace(/\s+/g, ' ').trim();
    if (!t && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) t = (el.value || '').trim();
    if (!t) continue;
    out.push({text: t, x: r.x, y: r.y, w: r.width, h: r.height});
  }
  return out;
}"""


def _tab(page, name):
    return page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}\s*-\s*\d+", re.I)).first


def _find_input(page):
    for n, sel in enumerate(INPUT_CANDIDATES):
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=25000 if n == 0 else 5000)
            return loc
        except PWTimeout:
            continue
    raise AgentError("The site's matter search box was not found; the page layout may have changed.")


def open_matter(page, matter):
    for idx in SEARCH_INDEXES:
        page.goto(SOURCE_URL, wait_until="domcontentloaded")
        field = _find_input(page)
        field.click()
        field.fill(matter + "\n")  # recorded session typed the number plus Enter
        buttons = page.get_by_role("button", name="Search")
        if buttons.count() <= idx:
            continue
        buttons.nth(idx).click()
        try:
            _tab(page, "Exhibits").wait_for(timeout=15000)
        except PWTimeout:
            continue
        try:
            page.get_by_text(matter).first.wait_for(timeout=5000)
        except PWTimeout:
            raise AgentError(f"The site opened a page, but I could not confirm it is matter {matter}.")
        return
    raise AgentError(f"I could not open matter {matter}. It may not exist, or the site did not respond as expected.")


def read_counts(page):
    counts = {}
    for name in CATEGORIES:
        tab = _tab(page, name)
        if tab.count() == 0:
            raise AgentError(f"The '{name}' tab was not found on the matter page.")
        label, n = parse_tab_count(tab.inner_text())
        if n is None:
            raise AgentError(f"Could not read the document count on the '{name}' tab.")
        counts[name] = n
    return counts


def ensure_rows(page, needed):
    """Scroll the list until `needed` GO GET IT buttons exist (lazy-loaded rows)."""
    btns = page.get_by_role("button", name=GO_GET_IT)
    last, stalls = -1, 0
    while True:
        n = btns.count()
        if n >= needed:
            return n
        stalls = stalls + 1 if n == last else 0
        if stalls >= 4:
            return n
        last = n
        if n:
            try:
                btns.nth(n - 1).scroll_into_view_if_needed(timeout=3000)
                btns.nth(n - 1).hover(timeout=3000)
            except PWTimeout:
                pass
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(600)


def _recover(page):
    try:
        close = page.get_by_role("button", name="Close", exact=True)
        if close.count():
            close.first.click(timeout=5000)
        page.locator(CURTAIN).first.wait_for(state="hidden", timeout=10000)
        return True
    except Exception:
        return False


def download_row(page, index, folder, seen):
    files = page.get_by_role("button", name=FILE_BUTTON)
    if files.count():
        raise AgentError("A download dialog was already open before clicking GO GET IT.")
    btn = page.get_by_role("button", name=GO_GET_IT).nth(index)
    btn.scroll_into_view_if_needed()
    btn.click()
    files.first.wait_for(timeout=30000)
    saved = []
    for j in range(files.count()):
        with page.expect_download(timeout=300000) as ev:
            files.nth(j).click()
        dl = ev.value
        name = dl.suggested_filename
        if name in seen:
            raise AgentError(f"The site returned {name} twice; row order may have changed.")
        path = Path(folder) / f"{index + 1:02d}_{safe_name(name)}"
        dl.save_as(path)
        if path.stat().st_size == 0:
            path.unlink()
            raise AgentError(f"{name} downloaded as an empty file.")
        seen.add(name)
        stem = Path(name).stem
        saved.append({"path": str(path), "filename": path.name, "id_matches_filename": ""})
        saved[-1]["_stem"] = stem
    close = page.get_by_role("button", name="Close", exact=True)
    close.click()
    page.locator(CURTAIN).first.wait_for(state="hidden", timeout=15000)
    return saved


def fetch(matter, category, output_dir, headless=False):
    folder = Path(output_dir) / f"{matter}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f')}"
    folder.mkdir(parents=True)
    result = {"matter": matter, "category": category, "counts": {}, "header": {}, "found_count": None,
              "downloads": [], "errors": [], "warnings": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True, viewport=VIEWPORT)
        page = context.new_page()
        page.set_default_timeout(20000)
        try:
            open_matter(page, matter)
            result["counts"] = read_counts(page)
            try:
                tab_box = _tab(page, "Exhibits").bounding_box()
                header, raw = parse_header(page.evaluate(JS_ITEMS), tab_box["y"])
                result["header"] = header
                if not header:
                    result["warnings"].append("Matter header could not be mapped reliably. Raw text: " + " / ".join(raw[:25]))
            except Exception as exc:
                result["warnings"].append(f"Matter header could not be read ({exc}).")
            total = result["counts"][category]
            if total:
                _tab(page, category).click()
                found = page.get_by_text(re.compile(r"Found Count:\s*\d+")).first
                found.wait_for()
                m = re.search(r"(\d+)", found.inner_text())
                result["found_count"] = int(m.group(1)) if m else None
                if result["found_count"] is not None and result["found_count"] != total:
                    result["warnings"].append(f"Tab shows {total} but the list says Found Count {result['found_count']}.")
                seen, fails = set(), 0
                for i in range(min(MAX_DOCS, total)):
                    have = ensure_rows(page, i + 1)
                    if have <= i:
                        result["warnings"].append(f"Only {have} rows could be loaded, so I stopped at {i}.")
                        break
                    try:
                        meta = row_meta(page.evaluate(JS_ITEMS), i)
                    except Exception:
                        meta = {}
                    try:
                        for s in download_row(page, i, folder, seen):
                            stem = s.pop("_stem")
                            s.update({k: v for k, v in meta.items() if k != "ext"})
                            s["id_matches_filename"] = (meta.get("row_doc_id") == stem) if meta.get("row_doc_id") else ""
                            result["downloads"].append(s)
                    except Exception as exc:
                        result["errors"].append({"index": i + 1, "error": str(exc).splitlines()[0][:200]})
                        fails += 1
                        if not _recover(page):
                            result["warnings"].append("The download dialog could not be closed, so I stopped.")
                            break
                        if fails >= 3:
                            result["warnings"].append("Stopped after 3 failed documents.")
                            break
        except Exception:
            try:
                page.screenshot(path=str(folder / "debug.png"), full_page=True)
                (folder / "debug.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            raise
        finally:
            context.close()
            browser.close()
    return result, package(result, folder), folder
