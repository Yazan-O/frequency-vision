import io
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app import api
from app.main import app

META = {"instance-type": "c8g.medium", "instance-id": "i-0123456789abcdef0", "ami-id": "ami-0123456789abcdef0",
        "placement/region": "us-east-1", "product-codes": "aajkmdd4qo3r7yhqg61a7aah9"}


@pytest.fixture
def fake_imds(monkeypatch):
    calls = []

    def urlopen(req, timeout=None):
        calls.append((req.get_method(), req.full_url, dict(req.header_items()), timeout))
        path = req.full_url.removeprefix(api.IMDS + "/")
        if path == "api/token":
            assert req.get_method() == "PUT"
            return io.BytesIO(b"tok")
        assert req.get_header("X-aws-ec2-metadata-token") == "tok"
        return io.BytesIO(META[path.removeprefix("meta-data/")].encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    api.imds.cache_clear()
    yield calls
    api.imds.cache_clear()


def test_cool_reports_instance_and_live_timing(fake_imds):
    r = TestClient(app).get("/api/cool", headers={"x-forwarded-for": "10.0.0.1"})
    assert r.status_code == 200
    d = r.json()
    assert d["instance"]["instance_type"] == "c8g.medium"
    assert d["instance"]["product_codes"] == META["product-codes"]
    assert all(t is not None and t <= 0.3 for *_, t in fake_imds)
    assert isinstance(d["threads"], int) and d["build_hal"]
    assert d["cool"] == d["cv2_file"].startswith("/opt/cool")
    t = d["timing"]
    assert t["status"] == "ok" and t["total_ms"] < 1000
    assert [o["op"] for o in t["ops"]] == ["GaussianBlur", "dft", "frequency_map"]
    assert all(1 <= o["runs"] <= 20 and o["p50_ms"] > 0 for o in t["ops"])
    assert t["fmap_pixels_passing_hum_test"] > 0
    assert "pip" not in t["input"]


def test_cool_without_ec2_metadata(monkeypatch):
    def down(req, timeout=None):
        raise OSError("no route")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    monkeypatch.setattr(api, "freq", None)
    api.imds.cache_clear()
    try:
        d = TestClient(app).get("/api/cool", headers={"x-forwarded-for": "10.0.0.2"}).json()
    finally:
        api.imds.cache_clear()
    assert d["instance"]["source"].startswith("not on EC2")
    assert d["timing"]["status"].startswith("unavailable")


def test_cool_is_rate_limited(monkeypatch, fake_imds):
    monkeypatch.setattr(api, "freq", None)
    c = TestClient(app)
    codes = [c.get("/api/cool", headers={"x-forwarded-for": "10.0.0.3"}).status_code for _ in range(api.LIMITS["cool"][0] + 1)]
    assert codes[:-1] == [200] * api.LIMITS["cool"][0] and codes[-1] == 429
