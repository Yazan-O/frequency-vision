from fastapi.testclient import TestClient

from app.main import app


def test_health_and_version():
    c = TestClient(app)
    assert c.get("/health").json()["ok"] is True
    v = c.get("/version").json()
    assert v["opencv"].startswith("5.")
