"""The phone remote's server (native/phone.py) without the studio: the page and
the state only with the link's key, commands checked before they are queued
(a slider's key, a number, a name - anything else dropped), a body past its
size refused, and the queue drained in order; the phone's camera - its page,
JPEG frames taken, anything else refused - over HTTPS with the certificate
the studio makes. On the loopback only.
Run with  python tests/test_phone.py  (or pytest).
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import phone                                   # noqa: E402


def _open():
    r = phone.PhoneRemote()
    r.open(0, key="testkey1", host="127.0.0.1")
    return r, f"http://127.0.0.1:{r.port}"


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(url, body):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def test_only_the_link_with_the_key_is_answered():
    r, base = _open()
    try:
        assert _get(base + "/")[0] == 403
        assert _get(base + "/?k=wrongkey")[0] == 403
        assert _get(base + "/state")[0] == 403
        assert _post(base + "/act", {"a": "stop"})[0] == 403
        code, page = _get(base + "/?k=testkey1")
        assert code == 200 and b"WLED Effects Studio" in page
        r.publish({"effect": "Rainbow", "bri": 200})
        code, body = _get(base + "/state?k=testkey1")
        assert code == 200 and json.loads(body) == {"effect": "Rainbow", "bri": 200}
        assert r.url("10.0.0.5") == f"http://10.0.0.5:{r.port}/?k=testkey1"
    finally:
        r.close()
    assert not r.is_open and r.url() == ""


def test_commands_are_checked_before_they_are_queued():
    r, base = _open()
    try:
        code, got = _post(base + "/act?k=testkey1", [
            {"a": "fx", "k": "sx", "v": 0.5},
            {"a": "fx", "k": "__class__", "v": 1},              # not a slider: dropped
            {"a": "effect", "v": "Fire 2012"},
            {"a": "effect", "v": ["not", "a", "name"]},         # not a name: dropped
            {"a": "bri", "v": "nan"},                           # not a number: dropped
            {"a": "rm -rf"},                                    # not an action: dropped
            {"a": "stop"}])
        assert code == 200 and got == {"taken": 3}, got
        assert r.drain() == [{"a": "fx", "k": "sx", "v": 0.5}, {"a": "effect", "v": "Fire 2012"}, {"a": "stop"}]
        assert r.drain() == []
        assert _post(base + "/act?k=testkey1", b"not json")[0] == 400
        assert _post(base + "/act?k=testkey1", b"[" + b" " * phone.MAX_BODY + b"]")[0] == 413
    finally:
        r.close()


def test_a_flood_keeps_only_the_newest():
    r = phone.PhoneRemote()
    r._queue([{"a": "bri", "v": float(i)} for i in range(phone.MAX_QUEUE + 50)])
    got = r.drain()
    assert len(got) == phone.MAX_QUEUE and got[-1]["v"] == phone.MAX_QUEUE + 49


def _jpeg(w=1280, h=720, fmt="JPEG"):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 40)).save(buf, fmt)
    return buf.getvalue()


def _send_frame(url, data, ctx=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "image/jpeg"})
    try:
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (ConnectionError, urllib.error.URLError):
        return "reset"                      # refused before the body was read: the sender may see only a reset


def test_camera_frames_are_checked():
    r, base = _open()
    r.camera = phone.CameraHub()
    try:
        cam = base + "/cam?k=testkey1"
        assert _send_frame(base + "/cam?k=wrongkey", b"x") == 403
        assert _send_frame(cam, b"not a picture") == 400
        assert _send_frame(cam, _jpeg(64, 64, "PNG")) == 400             # a JPEG only
        assert _send_frame(cam, b"\xff" * (phone.MAX_FRAME + 1)) in (413, "reset")
        assert r.camera.newest() == (None, 0) and r.camera.age() is None
        assert _send_frame(cam, _jpeg()) == 200
        img, n = r.camera.newest()
        assert n == 1 and img.size == (phone.FRAME_W, 360)                 # kept at most FRAME_W wide
        assert r.camera.age() < 5
        code, page = _get(base + "/camera?k=testkey1")
        assert code == 200 and b"getUserMedia" in page and b"isSecureContext" in page
        assert _get(base + "/camera")[0] == 403
    finally:
        r.close()


def test_the_camera_over_https():
    """Served over HTTPS with the certificate phone_tls makes (in a folder of the test's own): the page, a frame,
    and the links say https. Left out without the cryptography package."""
    from native import phone_tls
    if not phone_tls.available():
        print("     (no cryptography: the HTTPS test is left out)")
        return
    import ssl
    import tempfile
    tmp = tempfile.mkdtemp()
    keep = phone_tls._dir
    phone_tls._dir = lambda: tmp
    r = phone.PhoneRemote()
    r.camera = phone.CameraHub()
    try:
        r.open(0, key="testkey1", host="127.0.0.1", tls=True)
        assert r.tls and r.url("10.0.0.5").startswith("https://10.0.0.5:")
        assert r.camera_url("10.0.0.5") == f"https://10.0.0.5:{r.port}/camera?k=testkey1"
        assert os.path.exists(os.path.join(tmp, "cert.pem")) and os.path.exists(os.path.join(tmp, "key.pem"))
        ctx = phone._stdlib_context()(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(os.path.join(tmp, "cert.pem"))       # the certificate names 127.0.0.1: it verifies
        base = f"https://127.0.0.1:{r.port}"
        with urllib.request.urlopen(base + "/camera?k=testkey1", timeout=5, context=ctx) as resp:
            assert resp.status == 200 and b"getUserMedia" in resp.read()
        assert _send_frame(base + "/cam?k=testkey1", _jpeg(), ctx) == 200 and r.camera.count == 1
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{r.port}/?k=testkey1", timeout=5)
            raise AssertionError("plain HTTP was answered on the HTTPS port")
        except (urllib.error.URLError, OSError, ValueError):
            pass
        cert = open(os.path.join(tmp, "cert.pem"), "rb").read()
        assert phone_tls.ensure([phone.lan_address()]) and open(os.path.join(tmp, "cert.pem"), "rb").read() == cert   # kept
        phone_tls.ensure(["10.9.8.7"])
        assert open(os.path.join(tmp, "cert.pem"), "rb").read() != cert                                       # made again
    finally:
        r.close()
        phone_tls._dir = keep


def test_a_key_and_an_address():
    a, b = phone.new_key(), phone.new_key()
    assert a != b and len(a) == 8
    assert phone.lan_address().count(".") == 3


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e))
    sys.exit(1 if bad else 0)
