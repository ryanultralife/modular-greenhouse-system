import os
import tempfile
import unittest

from cryptography.fernet import Fernet

os.environ.setdefault("MGS_SECRET_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402

from api.app import create_app  # noqa: E402


class AuthTest(unittest.TestCase):
    def setUp(self):
        # Set in setUp (not import) so it can't be clobbered by another test
        # module that also sets MGS_ADMIN_PASSWORD at import time.
        os.environ["MGS_ADMIN_PASSWORD"] = "test-password-123"
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        # No dependency override here — we exercise the real auth flow.
        self.client = TestClient(create_app(db_url=f"sqlite:///{self._tmp.name}"))

    def tearDown(self):
        os.unlink(self._tmp.name)

    def _token(self):
        r = self.client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
        self.assertEqual(r.status_code, 200)
        return r.json()["token"]

    def test_login_success(self):
        self.assertTrue(self._token())

    def test_login_wrong_password(self):
        r = self.client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
        self.assertEqual(r.status_code, 401)

    def test_admin_endpoint_requires_token(self):
        r = self.client.get("/api/orders")
        self.assertEqual(r.status_code, 401)

    def test_admin_endpoint_with_token(self):
        token = self._token()
        r = self.client.get("/api/orders", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)

    def test_me_endpoint(self):
        token = self._token()
        r = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["username"], "admin")

    def test_invalid_token_rejected(self):
        r = self.client.get("/api/orders", headers={"Authorization": "Bearer garbage"})
        self.assertEqual(r.status_code, 401)

    def test_public_endpoints_stay_open(self):
        # No token, but public flow must still work.
        r = self.client.get("/api/public/models")
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/api/public/quote", json={"model": "barn_6_5", "shape": "straight", "runs": [8]})
        self.assertEqual(r.status_code, 200)

    def test_health_open(self):
        self.assertEqual(self.client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
