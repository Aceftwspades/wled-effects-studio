"""The phone remote's server (native/phone.py) without the studio: the page and
the state only with the link's key, commands checked before they are queued
(a slider's key, a number, a name - anything else dropped), a body past its
size refused, and the queue drained in order. On the loopback only.
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
