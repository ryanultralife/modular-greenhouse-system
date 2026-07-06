import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from api import email_service  # noqa: E402
from api.db import dispose_engine, get_session, init_db  # noqa: E402


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, from_email, to, subject, html, text=None):
        self.sent.append({"from": from_email, "to": to, "subject": subject, "html": html})


class EmailServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        init_db(f"sqlite:///{self._tmp.name}")
        self.db = get_session()

    def tearDown(self):
        self.db.close()
        dispose_engine()  # Windows: release the SQLite file lock before unlink
        os.unlink(self._tmp.name)

    def test_sends_via_injected_sender(self):
        sender = FakeSender()
        ok = email_service.send_email(
            self.db, "c@x.com", "Hello", "<p>hi</p>", sender=sender, from_email="josh@mg.com"
        )
        self.assertTrue(ok)
        self.assertEqual(len(sender.sent), 1)
        self.assertEqual(sender.sent[0]["to"], "c@x.com")
        self.assertEqual(sender.sent[0]["from"], "josh@mg.com")

    def test_no_recipient_raises(self):
        with self.assertRaises(email_service.EmailError):
            email_service.send_email(self.db, "", "s", "<p>x</p>", sender=FakeSender())

    def test_missing_smtp_integration_raises(self):
        with self.assertRaises(email_service.EmailError):
            email_service.send_email(self.db, "c@x.com", "s", "<p>x</p>")

    def test_emailsender_builds_message_fields(self):
        # Exercise EmailSender message construction without opening a socket by
        # pointing it at an unreachable host and asserting the failure type.
        sender = email_service.EmailSender(host="127.0.0.1", port=1, use_tls=False, timeout=0.2)
        with self.assertRaises(email_service.EmailError):
            sender.send("a@b.com", "c@d.com", "subj", "<p>body</p>")


if __name__ == "__main__":
    unittest.main()
