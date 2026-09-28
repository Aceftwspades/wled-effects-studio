"""The update check without the network (native/update.py): a release's
file for this platform - the Windows zip, the Linux tarball, nothing for
macOS - and the check read from a releases JSON on disk
(STUDIO_UPDATE_URL, as a test points it anywhere). And the packaged Linux
app's children: the library path they get (native/procs.py).
"""
import json
import os
import pathlib
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import update, version                 # noqa: E402

BASE = "https://github.com/Aceftwspades/wled-effects-studio/releases/download/v9.9.9/"
ASSETS = [{"name": "WLED_Effects_Studio_linux.tar.gz", "browser_download_url": BASE + "WLED_Effects_Studio_linux.tar.gz"},
          {"name": "WLED_Effects_Studio.zip", "browser_download_url": BASE + "WLED_Effects_Studio.zip"},
          {"name": "notes.txt", "browser_download_url": BASE + "notes.txt"}]


def test_each_platform_gets_its_own_file():
    assert update.asset_for(ASSETS, "win32") == BASE + "WLED_Effects_Studio.zip"          # not the tarball listed first
    assert update.asset_for(ASSETS, "linux") == BASE + "WLED_Effects_Studio_linux.tar.gz"
    assert update.asset_for(ASSETS, "darwin") is None                                       # macOS: from a checkout
    assert update.asset_for(ASSETS[1:], "linux") is None                                   # an older release: Windows only
    assert update.asset_for([], "win32") is None and update.asset_for(None, "linux") is None


def test_the_check_reads_a_release():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "latest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"tag_name": "v9.9.9", "name": "9.9.9", "body": "  what is new  ", "html_url": BASE, "assets": ASSETS}, f)
        was = os.environ.get("STUDIO_UPDATE_URL")
        os.environ["STUDIO_UPDATE_URL"] = pathlib.Path(path).as_uri()
        try:
            u = update.check()
        finally:
            if was is None:
                os.environ.pop("STUDIO_UPDATE_URL", None)
            else:
                os.environ["STUDIO_UPDATE_URL"] = was
    assert u and u["tag"] == "v9.9.9" and u["newer"] and u["notes"] == "what is new" and u["name"] == "9.9.9", u
    assert u["asset"] == update.asset_for(ASSETS), u                     # this machine's own file
    assert not version.newer("v0.0.1")


def test_no_release_to_be_had():
    was = os.environ.get("STUDIO_UPDATE_URL")
    os.environ["STUDIO_UPDATE_URL"] = pathlib.Path(os.path.join(tempfile.gettempdir(), "no_such_release.json")).as_uri()
    try:
        assert update.check() is None
    finally:
        if was is None:
            os.environ.pop("STUDIO_UPDATE_URL", None)
        else:
            os.environ["STUDIO_UPDATE_URL"] = was


def test_the_packaged_linux_apps_children_get_their_own_libraries():
    from native import procs
    app = "/opt/WLED Effects Studio/_internal"
    env = {"PATH": "/usr/bin", "LD_LIBRARY_PATH": app + ":/usr/local/lib", "LD_LIBRARY_PATH_ORIG": "/usr/local/lib"}
    e = procs.child_env(env, frozen=True, platform="linux")
    assert e["LD_LIBRARY_PATH"] == "/usr/local/lib" and e["PATH"] == "/usr/bin", e       # as it was before the bootloader
    assert env["LD_LIBRARY_PATH"].startswith(app)                                         # the caller's left alone
    e = procs.child_env({"PATH": "/usr/bin", "LD_LIBRARY_PATH": app}, frozen=True, platform="linux")
    assert "LD_LIBRARY_PATH" not in e, e                                                   # there was none
    assert procs.child_env(env, frozen=False, platform="linux") is env                    # from a checkout: as it came
    assert procs.child_env(env, frozen=True, platform="win32") is env                     # Windows: no such path
    assert procs.child_env(None, frozen=False, platform="linux") is None


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                failed += 1; print("FAIL", name, str(e)[:2000])
    sys.exit(1 if failed else 0)
