"""Тесты CSRF/DNS-rebinding защиты: loopback-only Origin/Host (main.py)."""
from __future__ import annotations


# ---------- Чужой Origin ----------

def test_foreign_origin_forbidden(client):
    resp = client.get("/api/settings", headers={"Origin": "https://evil.com"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden_origin"


def test_post_check_with_foreign_origin_blocked_before_validation(client):
    """«Простой» multipart-POST без preflight режется до валидации файлов."""
    resp = client.post(
        "/api/check",
        files={"files": ("x.docx", b"garbage", "application/octet-stream")},
        headers={"Origin": "https://evil.com"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden_origin"


# ---------- Легальные Origin ----------

def test_loopback_origins_allowed(client):
    for origin in (
        "http://127.0.0.1:8787",   # same-origin (prod/pywebview)
        "http://localhost:5173",   # dev-прокси Vite
        "http://localhost:5174",
    ):
        resp = client.get("/api/settings", headers={"Origin": origin})
        assert resp.status_code == 200, origin


def test_no_origin_allowed(client):
    """curl и pywebview same-origin GET шлют запрос без Origin."""
    assert client.get("/api/settings").status_code == 200


# ---------- DNS-rebinding (чужой Host без Origin) ----------

def test_foreign_host_forbidden(client):
    resp = client.get("/api/settings", headers={"Host": "evil.com"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden_host"
