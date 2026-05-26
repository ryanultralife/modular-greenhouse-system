import os
import unittest

# Pin a master key so encryption is deterministic and no key file is written.
from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from api import security  # noqa: E402


class SecurityTest(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        creds = {"secret_key": "sk_live_abc123", "realm_id": "9988"}
        blob = security.encrypt_dict(creds)
        self.assertNotIn("sk_live_abc123", blob)  # ciphertext, not plaintext
        self.assertEqual(security.decrypt_dict(blob), creds)

    def test_mask_value(self):
        self.assertEqual(security.mask_value("sk_live_abcd1234"), "****1234")
        self.assertEqual(security.mask_value("xy"), "****")
        self.assertEqual(security.mask_value(""), "")

    def test_decrypt_bad_token_raises(self):
        with self.assertRaises(ValueError):
            security.decrypt_dict("not-a-valid-token")


if __name__ == "__main__":
    unittest.main()
