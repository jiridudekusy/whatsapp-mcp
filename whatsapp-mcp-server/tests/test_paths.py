"""Host/container path mapping for media (WHATSAPP_PATH_MAP).

The server may run in a container while clients name files by host paths; without the
mapping send_file answered "Media file not found" for every file on the host.
"""

import whatsapp


def test_no_map_is_identity(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PATH_MAP", raising=False)
    assert whatsapp.to_local_path("/Users/me/x.jpg") == "/Users/me/x.jpg"
    assert whatsapp.to_client_path("/app/store/y.jpg") == "/app/store/y.jpg"
    assert whatsapp.media_not_found("/x") == "Media file not found: /x"


def test_map_translates_both_ways(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PATH_MAP", "/Users/me/outbox=/app/outbox; /Users/me/Downloads/=/mnt/dl")
    assert whatsapp.to_local_path("/Users/me/outbox/a.pdf") == "/app/outbox/a.pdf"
    assert whatsapp.to_local_path("/Users/me/Downloads/b.png") == "/mnt/dl/b.png"
    assert whatsapp.to_local_path("/Users/me/outboxer/c") == "/Users/me/outboxer/c"   # prefix must be a directory
    assert whatsapp.to_local_path("/elsewhere/d") == "/elsewhere/d"
    assert whatsapp.to_client_path("/app/outbox/a.pdf") == "/Users/me/outbox/a.pdf"


def test_send_file_reports_allowed_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("WHATSAPP_PATH_MAP", f"/Users/me/outbox={tmp_path}")
    ok, msg = whatsapp.send_file("420111222333", "/Users/me/outbox/missing.jpg")
    assert not ok
    assert "Media file not found" in msg and "/Users/me/outbox" in msg


def test_send_file_translates_before_checking(monkeypatch, tmp_path):
    (tmp_path / "pic.jpg").write_bytes(b"x")
    monkeypatch.setenv("WHATSAPP_PATH_MAP", f"/Users/me/outbox={tmp_path}")
    monkeypatch.setattr(whatsapp, "WHATSAPP_API_BASE_URL", "http://127.0.0.1:9/api")  # nothing listens
    ok, msg = whatsapp.send_file("420111222333", "/Users/me/outbox/pic.jpg")
    assert not ok and "Media file not found" not in msg        # got past the file check
