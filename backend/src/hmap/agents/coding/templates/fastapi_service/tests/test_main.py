import importlib.util
import unittest

HAVE_DEPS = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx"))


@unittest.skipUnless(HAVE_DEPS, "fastapi / httpx not installed here (make coding-venv)")
class ServiceTest(unittest.TestCase):
    def setUp(self):
        from app.main import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app)

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_create_and_get(self):
        created = self.client.post("/items", json={"name": "pen"}).json()
        self.assertEqual(self.client.get(f"/items/{created['id']}").json()["name"], "pen")
        self.assertEqual(self.client.get("/items/999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
