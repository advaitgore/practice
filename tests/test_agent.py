import tempfile
import unittest
import zipfile
from pathlib import Path
from email.message import EmailMessage
from document_agent import parse_request, counts_from, safe_name, package, build_reply

class Tests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_request('M12205 other docs'), ('M12205', 'Other Documents'))
        self.assertEqual(parse_request('m12383 audio'), ('M12383', 'Recordings'))
    def test_invalid(self):
        for text in ('M1220 exhibits', 'M122050 exhibits', 'M12205 exhibits transcripts', 'M12205 M12383 exhibits'):
            with self.assertRaises(ValueError): parse_request(text)
    def test_quotes(self):
        self.assertEqual(parse_request('M12205 exhibits\n> M12383 audio'), ('M12205', 'Exhibits'))
    def test_counts(self):
        counts = counts_from('Exhibits - 13 Key Documents - 5 Other Documents - 21 Transcripts - 0 Recordings - 0')
        self.assertEqual(counts['Other Documents'], 21)
        with self.assertRaises(ValueError): counts_from('Exhibits - 0')
    def test_filename(self):
        self.assertEqual(safe_name('../../evil.pdf'), 'evil.pdf')
    def test_package(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'file.pdf'; p.write_bytes(b'test')
            result = dict(matter='M12205', category='Exhibits', counts={'Exhibits':1}, downloads=[dict(path=str(p), title='Test')], errors=[])
            archive = package(result, d)
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), {'file.pdf', 'manifest.csv', 'coverage.json'})
                self.assertIn(b'9f86d081', z.read('manifest.csv'))
    def test_reply(self):
        original = EmailMessage(); original['From']='tester@example.com'; original['Subject']='Request'; original['Message-ID']='<test@example.com>'
        msg = build_reply(original, 'agent@example.com', 'Hello')
        self.assertEqual(msg['To'], 'tester@example.com')
        self.assertEqual(msg['In-Reply-To'], '<test@example.com>')
