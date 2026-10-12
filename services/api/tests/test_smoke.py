def test_health_is_public(app):
    from fastapi.testclient import TestClient

    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
