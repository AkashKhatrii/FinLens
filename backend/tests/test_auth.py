"""HTTP Basic gate: off locally, on when FINLENS_PASSWORD is set."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class PasswordGateTest(unittest.TestCase):
    def test_open_when_password_unset(self):
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("FINLENS_PASSWORD", None)
        try:
            client = TestClient(app)
            res = client.get("/")
            self.assertEqual(res.status_code, 200)
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["status"], "ok")
        finally:
            env.stop()

    def test_401_when_password_set_and_missing_or_wrong(self):
        with patch.dict(os.environ, {"FINLENS_PASSWORD": "secret-gate"}, clear=False):
            client = TestClient(app)
            missing = client.get("/")
            self.assertEqual(missing.status_code, 401)
            self.assertIn("Basic", missing.headers.get("www-authenticate", ""))
            wrong = client.get("/", auth=("finlens", "nope"))
            self.assertEqual(wrong.status_code, 401)
            wrong_user = client.get("/", auth=("admin", "secret-gate"))
            self.assertEqual(wrong_user.status_code, 401)

    def test_health_stays_open_when_password_set(self):
        with patch.dict(os.environ, {"FINLENS_PASSWORD": "secret-gate"}, clear=False):
            client = TestClient(app)
            res = client.get("/api/health")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "ok")

    def test_correct_basic_auth_is_accepted(self):
        with patch.dict(os.environ, {"FINLENS_PASSWORD": "secret-gate"}, clear=False):
            client = TestClient(app)
            res = client.get("/", auth=("finlens", "secret-gate"))
            self.assertEqual(res.status_code, 200)
            tradebook = client.get("/api/tradebook", auth=("finlens", "secret-gate"))
            self.assertEqual(tradebook.status_code, 200)


if __name__ == "__main__":
    unittest.main()
