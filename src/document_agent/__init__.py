import argparse
import csv
import email
import getpass
import hashlib
import imaplib
import json
import os
import re
import smtplib
import sqlite3
import ssl
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import default
from email.utils import parseaddr
from pathlib import Path

CATEGORIES = ('Exhibits', 'Key Documents', 'Other Documents', 'Transcripts', 'Recordings')
PATTERNS = (r'\bexhibits?\b', r'\bkey (?:documents?|docs?)\b', r'\bother (?:documents?|docs?)\b', r'\btranscripts?\b', r'\b(?:recordings?|audio(?: files?)?)\b')
HOME = Path.home() / '.practice-document-agent'
URL = 'https://uarb.novascotia.ca/fmi/webd/UARB15'

def parse_request(text):
    text = text.split('\nOn ')[0].split('-----Original Message-----')[0]
    text = '\n'.join(x for x in text.splitlines() if not x.lstrip().startswith('>'))
    matters = set(re.findall(r'\bM[ -]?(\d{5})\b', text, re.I))
    kinds = [k for k, p in zip(CATEGORIES, PATTERNS) if re.search(p, text, re.I)]
    if len(matters) != 1 or len(kinds) != 1:
        raise ValueError('Include exactly one matter number (M12205) and one category: ' + ', '.join(CATEGORIES))
    return 'M' + matters.pop(), kinds[0]

def counts_from(text):
    counts = {}
    for name in CATEGORIES:
        m = re.search(re.escape(name) + r'\s*[-–:]\s*(\d+)', text, re.I)
        if not m:
            raise ValueError('Cannot verify count for ' + name)
        counts[name] = int(m.group(1))
    return counts

def safe_name(name):
    name = re.split(r'[/\\]', name)[-1]
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:160] or 'document.bin'

def package(result, folder):
    folder = Path(folder)
    manifest = folder / 'manifest.csv'
    with manifest.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['filename', 'title', 'bytes', 'sha256'])
        for item in result['downloads']:
            path = Path(item['path'])
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            writer.writerow([path.name, item['title'], path.stat().st_size, digest])
    report = {k: v for k, v in result.items() if k != 'downloads'}
    report.update(downloaded=len(result['downloads']), retrieved_at=datetime.now(timezone.utc).isoformat(), selection='First up to 10 in displayed order', warning='Category counts may overlap; their sum is not a unique-file count.')
    coverage = folder / 'coverage.json'
    coverage.write_text(json.dumps(report, indent=2), encoding='utf-8')
    target = folder / (result['matter'] + '_documents.zip')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in result['downloads']:
            archive.write(item['path'], Path(item['path']).name)
        archive.write(manifest, manifest.name)
        archive.write(coverage, coverage.name)
    return target

def fetch(matter, category, args):
    from playwright.sync_api import sync_playwright
    selectors = json.loads(Path(args.selectors).read_text(encoding='utf-8'))
    if any('REPLACE_' in str(v) for v in selectors.values()):
        raise ValueError('Verify live-site selectors before running fetch; see README.')
    folder = Path(args.output) / (matter + '_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%f'))
    folder.mkdir(parents=True)
    result = dict(matter=matter, category=category, counts={}, metadata='', downloads=[], errors=[])
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(20000)
        try:
            page.goto(URL, wait_until='domcontentloaded')
            page.locator(selectors['input']).fill(matter)
            page.locator(selectors['search']).click()
            page.get_by_text(re.compile(re.escape(matter), re.I)).first.wait_for()
            result['counts'] = counts_from(page.locator('body').inner_text())
            result['metadata'] = page.locator(selectors['header']).inner_text()
            if result['counts'][category]:
                page.get_by_text(re.compile(r'^' + re.escape(category) + r'\s*[-–:]\s*\d+\s*$', re.I)).click()
                rows = page.locator(selectors['rows'])
                rows.first.wait_for()
                target = min(10, result['counts'][category])
                if rows.count() < target:
                    raise ValueError('Fewer rows loaded than required. Implement/verify scrolling or pagination first.')
                for index in range(target):
                    row = rows.nth(index)
                    title = row.inner_text()
                    try:
                        row.get_by_text(re.compile('GO GET IT', re.I)).click()
                        with page.expect_download(timeout=120000) as event:
                            page.locator(selectors['filename']).click()
                        download = event.value
                        path = folder / (f'{index+1:02d}_' + safe_name(download.suggested_filename))
                        download.save_as(path)
                        if not path.stat().st_size:
                            raise ValueError('Empty download')
                        result['downloads'].append(dict(path=str(path), title=title))
                    except Exception as exc:
                        result['errors'].append(dict(index=index+1, error=str(exc)))
                        break
        except Exception:
            page.screenshot(path=str(folder / 'debug.png'), full_page=True)
            (folder / 'debug.html').write_text(page.content(), encoding='utf-8')
            raise
        finally:
            context.close()
            browser.close()
    return result, package(result, folder)

def report_text(result):
    return (f"Matter: {result['matter']}\nRequested: {result['category']}\n\n{result['metadata']}\n\n"
            + '\n'.join(f'{k}: {v}' for k, v in result['counts'].items())
            + f"\nCategory-entry sum: {sum(result['counts'].values())} (not a verified unique-file total).\nDownloaded: {len(result['downloads'])} of {result['counts'][result['category']]}.\nFailures: {len(result['errors'])}.\nSelection: first up to 10 in displayed order. Manifest and coverage report are attached inside the ZIP.\n")

def build_reply(original, address, body, attachment=None):
    recipient = parseaddr(original.get('Reply-To') or original.get('From', ''))[1]
    if not recipient or recipient.lower() == address.lower():
        raise ValueError('Invalid destination')
    msg = EmailMessage()
    msg['From'], msg['To'] = address, recipient
    subject = str(original.get('Subject', 'Document request'))
    msg['Subject'] = subject if subject.lower().startswith('re:') else 'Re: ' + subject
    if original.get('Message-ID'):
        msg['In-Reply-To'] = original['Message-ID']
        msg['References'] = str(original.get('References', '')) + ' ' + original['Message-ID']
    msg['Auto-Submitted'] = 'auto-replied'
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype='application', subtype='zip', filename=attachment.name)
    if len(msg.as_bytes()) > 24000000:
        raise ValueError('Serialized email exceeds conservative delivery limit. No files were silently removed.')
    return msg

def listen(args):
    config = json.loads((HOME / 'config.json').read_text())
    address = config['email']
    password = (os.environ.get('AGENT_APP_PASSWORD') or getpass.getpass('Gmail app password (hidden, not saved): ')).replace(' ', '')
    db = sqlite3.connect(HOME / 'state.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT)')
    print('Listening. Keep this process and laptop running. Ctrl+C stops it.')
    while True:
        try:
            with imaplib.IMAP4_SSL('imap.gmail.com', 993) as conn:
                conn.login(address, password)
                conn.select('INBOX')
                status, data = conn.uid('search', None, 'UNSEEN')
                if status != 'OK':
                    raise RuntimeError('Inbox search failed')
                for uid in data[0].split():
                    status, chunks = conn.uid('fetch', uid, '(BODY.PEEK[])')
                    if status != 'OK':
                        continue
                    raw = next(x[1] for x in chunks if isinstance(x, tuple))
                    original = email.message_from_bytes(raw, policy=default)
                    if original.get('Auto-Submitted', 'no').lower() != 'no' or original.get('List-ID'):
                        continue
                    if parseaddr(original.get('From', ''))[1].lower() == address.lower():
                        continue
                    key = str(original.get('Message-ID') or hashlib.sha256(raw).hexdigest())
                    if db.execute('SELECT 1 FROM jobs WHERE id=?', (key,)).fetchone():
                        continue
                    db.execute('INSERT INTO jobs VALUES (?, ?)', (key, 'processing'))
                    db.commit()
                    try:
                        part = original.get_body(preferencelist=('plain',))
                        text = str(original.get('Subject', '')) + '\n' + (part.get_content() if part else '')
                        attachment = None
                        try:
                            matter, category = parse_request(text)
                        except ValueError as exc:
                            body = str(exc)
                        else:
                            result, attachment = fetch(matter, category, args)
                            body = report_text(result)
                        outgoing = build_reply(original, address, body, attachment)
                        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context()) as smtp:
                            smtp.login(address, password)
                            smtp.send_message(outgoing)
                        db.execute('UPDATE jobs SET status=? WHERE id=?', ('sent', key))
                    except Exception as exc:
                        db.execute('UPDATE jobs SET status=? WHERE id=?', ('needs_review', key))
                        print('Job needs review:', key, str(exc), file=sys.stderr)
                    db.commit()
        except Exception as exc:
            print('Mailbox error:', str(exc), file=sys.stderr)
        time.sleep(args.interval)

def main():
    parser = argparse.ArgumentParser(description='Draft public-document email agent')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('setup')
    for name in ('fetch', 'run'):
        child = sub.add_parser(name)
        child.add_argument('--selectors', default='selectors.local.json')
        child.add_argument('--output', default='artifacts')
        child.add_argument('--headless', action='store_true')
        if name == 'fetch':
            child.add_argument('matter')
            child.add_argument('category')
        else:
            child.add_argument('--interval', type=int, default=30)
    args = parser.parse_args()
    if args.command == 'setup':
        HOME.mkdir(parents=True, exist_ok=True)
        address = input('Burner Gmail address: ').strip()
        (HOME / 'config.json').write_text(json.dumps({'email': address}))
        subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)
        print('Setup complete. Password requested at runtime, not saved.')
    elif args.command == 'fetch':
        matter, category = parse_request(args.matter + ' ' + args.category)
        result, archive = fetch(matter, category, args)
        print(report_text(result))
        print('ZIP:', archive.resolve())
    else:
        listen(args)
