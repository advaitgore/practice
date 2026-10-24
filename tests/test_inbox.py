import sqlite3
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from document_agent import cli, mailbox
from document_agent.triage import triage

ME = "burner@gmail.com"


def mail(sender, subject="", body="", msgid=None, **headers):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, ME, subject
    m["Message-ID"] = msgid or f"<{abs(hash((sender, subject, body)))}@test>"
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    return m


class Triage(unittest.TestCase):
    def test_real_request(self):
        v, _ = triage(mail("Paula <paula@senpilot.com>", "Task", "Hi Agent, Can you give me Other Documents files from M12205? Thanks!"), ME)
        self.assertEqual(v, "request")

    def test_incomplete_request_still_a_request(self):
        self.assertEqual(triage(mail("a@b.com", "M12205 please", "thanks"), ME)[0], "request")

    def test_google_notifications_ignored(self):
        for sender in ("Google <privacy-noreply@policies.google.com>", "Hangouts <noreply-cd7fe6bc@plus.google.com>"):
            self.assertEqual(triage(mail(sender, "Improvements to our Privacy Policy", "This month we are updating"), ME)[0], "ignore")

    def test_bounce_and_automated(self):
        self.assertEqual(triage(mail("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Delivery Status Notification", "Address not found"), ME)[0], "ignore")
        self.assertEqual(triage(mail("bot@example.com", "x", "M12205 exhibits", Auto_Submitted="auto-replied"), ME)[0], "ignore")
        self.assertEqual(triage(mail("news@example.com", "x", "M12205 exhibits", List_Unsubscribe="<mailto:x@y.z>"), ME)[0], "ignore")

    def test_marketing_mentioning_exhibits_ignored(self):
        self.assertEqual(triage(mail("sales@museum.com", "Visit our exhibits", "New exhibits open this weekend"), ME)[0], "ignore")

    def test_own_message_ignored(self):
        self.assertEqual(triage(mail(ME, "M12205 exhibits", "x"), ME)[0], "ignore")

    def test_quoted_text_does_not_count(self):
        self.assertEqual(triage(mail("a@b.com", "hello", "Thanks!\n> M12205 exhibits"), ME)[0], "ignore")

    def test_html_only_request(self):
        m = EmailMessage()
        m["From"], m["Subject"] = "a@b.com", "hi"
        m.set_content("<p>Agent: please send <b>Exhibits</b> for M12205</p>", subtype="html")
        self.assertEqual(triage(m, ME)[0], "request")


def make_db():
    db = sqlite3.connect(":memory:")
    cli.init_db(db)
    return db


def args():
    return SimpleNamespace(output="artifacts", headless=True)


class Handle(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.tmp = tempfile.TemporaryDirectory()
        self.zip = Path(self.tmp.name) / "M12205_Other_Documents.zip"
        self.zip.write_bytes(b"zip")
        result = {"matter": "M12205", "category": "Other Documents", "downloads": [{}], "errors": [], "counts": {}}
        self.fetch = mock.patch.object(cli, "fetch", return_value=(result, self.zip, Path(self.tmp.name))).start()
        mock.patch.object(mailbox, "send", side_effect=lambda a, p, m: self.sent.append(m)).start()
        mock.patch.object(cli, "log", lambda *a: None).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.tmp.cleanup)

    def run_one(self, msg, db=None, uid=1):
        db = db or make_db()
        cli.handle(uid, msg.as_bytes(), ME, "pw", db, args())
        return db

    def test_unrelated_mail_gets_no_reply(self):
        self.run_one(mail("Google <privacy-noreply@policies.google.com>", "Privacy", "policy update"))
        self.assertEqual(self.sent, [])
        self.fetch.assert_not_called()

    def test_request_gets_one_reply_with_zip(self):
        self.run_one(mail("Paula <paula@senpilot.com>", "Task", "Can you give me Other Documents files from M12205?"))
        self.assertEqual(len(self.sent), 1)
        reply = self.sent[0]
        self.assertEqual(reply["To"], "paula@senpilot.com")
        self.assertEqual([p.get_filename() for p in reply.iter_attachments()], ["M12205_Other_Documents.zip"])
        self.fetch.assert_called_once()

    def test_incomplete_request_gets_clarification_without_fetch(self):
        self.run_one(mail("a@b.com", "M12205 please", "thanks"))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("exactly one document type", self.sent[0].get_content())
        self.fetch.assert_not_called()

    def test_same_message_not_answered_twice(self):
        db = make_db()
        m = mail("a@b.com", "M12205 exhibits", "x", msgid="<same@test>")
        self.run_one(m, db, 1)
        self.run_one(m, db, 2)
        self.assertEqual(len(self.sent), 1)

    def test_per_sender_hourly_limit(self):
        db = make_db()
        for i in range(8):
            self.run_one(mail("loop@example.com", f"M12205 exhibits {i}", "x", msgid=f"<{i}@t>"), db, i)
        self.assertEqual(len(self.sent), cli.MAX_REPLIES_PER_SENDER_PER_HOUR)

    def test_fetch_failure_still_replies_politely(self):
        self.fetch.side_effect = RuntimeError("boom")
        self.run_one(mail("a@b.com", "M12205 exhibits", "x"))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("could not complete", self.sent[0].get_content())


class FakeIMAP:
    log = []
    uids = [1, 2, 3, 4, 5]

    def __init__(self, host, port):
        FakeIMAP.log = []

    def login(self, a, p):
        FakeIMAP.log.append("login")

    def select(self, name, readonly=False):
        FakeIMAP.log.append(("select", readonly))
        return "OK", [b"5"]

    def response(self, name):
        return name, [b"7"]

    def uid(self, cmd, *a):
        FakeIMAP.log.append(cmd)
        if cmd == "search":
            return "OK", [" ".join(map(str, FakeIMAP.uids)).encode()]
        if cmd == "fetch":
            return "OK", [(b"x", f"From: a@b.com\r\nSubject: uid {a[0]}\r\n\r\nbody".encode()), b")"]
        raise AssertionError("unexpected IMAP command " + cmd)

    def logout(self):
        FakeIMAP.log.append("logout")


class Poll(unittest.TestCase):
    def setUp(self):
        mock.patch.object(mailbox.imaplib, "IMAP4_SSL", FakeIMAP).start()
        self.addCleanup(mock.patch.stopall)

    def test_first_run_sets_baseline_and_returns_no_mail(self):
        v, mx, new = mailbox.poll(ME, "pw", None, None)
        self.assertEqual((v, mx, new), (7, 5, []))
        self.assertNotIn("fetch", FakeIMAP.log)

    def test_only_newer_mail_returned(self):
        v, mx, new = mailbox.poll(ME, "pw", 3, 7)
        self.assertEqual([u for u, _ in new], [4, 5])

    def test_changed_uidvalidity_resets_baseline(self):
        v, mx, new = mailbox.poll(ME, "pw", 3, 99)
        self.assertEqual(new, [])

    def test_inbox_opened_read_only_and_never_modified(self):
        mailbox.poll(ME, "pw", 3, 7)
        self.assertIn(("select", True), FakeIMAP.log)
        self.assertNotIn("store", FakeIMAP.log)

    def test_recent_returns_newest_n(self):
        self.assertEqual([u for u, _ in mailbox.recent(ME, "pw", 2)], [4, 5])


class Reply(unittest.TestCase):
    def test_reply_goes_to_from_address_not_reply_to(self):
        m = mail("Paula <p@example.com>", "Request", "x", Reply_To="evil@example.com")
        self.assertEqual(mailbox.build_reply(m, ME, "hi")["To"], "p@example.com")


if __name__ == "__main__":
    unittest.main()
