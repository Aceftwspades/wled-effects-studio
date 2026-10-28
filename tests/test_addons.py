"""The VJ's add-on looks (native/addons.py), from packs on disk: packs.json read with what is not whole left out,
a pack installed whole or a look at a time, a file that is not the list's refused, a changed one seen as an
update, a look and a pack removed; the installed looks read into the VJ beside the project's own, where each
comes from, the studio-wide favourites and the browser's sections. Run with  python tests/test_addons.py  (or
pytest).
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from native import addons, gallery, project, vj, vj_looks       # noqa: E402

MILK = "[preset00]\nzoom=1.01\nper_frame_1=rot = rot + 0.01*(bass_att - 1);\n"
GLSL = ("// NAME: Test rings (someone)\nvoid mainImage(out vec4 fragColor, in vec2 fragCoord) {\n"
        "    vec2 uv = fragCoord / iResolution.xy;\n"
        "    fragColor = vec4(0.5 + 0.5 * sin(10.0 * length(uv - 0.5) - iTime), uv, 1.0);\n}\n")


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _make(folder, extra=None):
    """A gallery of two packs in `folder` (its file:// address); `extra`: more raw packs.json entries."""
    files = {("test-milk", "Spin one.milk"): MILK.encode(), ("test-milk", "Spin two.milk"): MILK.replace("1.01", "0.99").encode(),
             ("test-toy-nc", "Test rings by someone.glsl"): GLSL.encode()}
    for (pid, f), data in files.items():
        os.makedirs(os.path.join(folder, "looks", pid), exist_ok=True)
        with open(os.path.join(folder, "looks", pid, f), "wb") as fh:
            fh.write(data)

    def items(pid):
        return [{"file": f, "author": "someone", "licence": "test", "sha256": _sha(d)}
                for (p, f), d in files.items() if p == pid]
    packs = [{"id": "test-milk", "name": "Test: milk", "kind": "milkdrop", "description": "Two presets.",
              "licence": "test", "items": items("test-milk")},
             {"id": "test-toy-nc", "name": "Test: toys", "kind": "shadertoy", "description": "One shader.",
              "licence": "CC BY-NC-SA 3.0", "items": items("test-toy-nc")}] + (extra or [])
    with open(os.path.join(folder, "packs.json"), "w", encoding="utf-8") as fh:
        json.dump({"packs": 1, "list": packs}, fh)
    return "file:///" + folder.replace(os.sep, "/").lstrip("/") + "/"


def _with_packs(fn, extra=None):
    d = tempfile.mkdtemp(prefix="studio_packs_")
    home = tempfile.mkdtemp(prefix="studio_packs_home_")
    old_url, old_home, old_studio = os.environ.get("STUDIO_GALLERY_URL"), addons.paths.HOME, project.STUDIO_FILE
    try:
        os.environ["STUDIO_GALLERY_URL"] = _make(d, extra)
        addons.paths.HOME = home
        project.STUDIO_FILE = os.path.join(home, "studio.json")
        fn(d)
    finally:
        if old_url is None:
            os.environ.pop("STUDIO_GALLERY_URL", None)
        else:
            os.environ["STUDIO_GALLERY_URL"] = old_url
        addons.paths.HOME = old_home
        project.STUDIO_FILE = old_studio
        shutil.rmtree(d, ignore_errors=True); shutil.rmtree(home, ignore_errors=True)


def test_packs_json_keeps_only_whole_packs():
    good = "b" * 64
    extra = [{"id": "../evil", "items": [{"file": "x.milk", "sha256": good}]},
             {"id": "no-items", "items": []},
             {"id": "bad-files", "items": [{"file": "../up.milk", "sha256": good}, {"file": "run.py", "sha256": good},
                                           {"file": "nohash.milk"}, {"file": "C:\\x.glsl", "sha256": good}]},
             {"id": "test-milk", "items": [{"file": "again.milk", "sha256": good}]}, "nonsense"]

    def check(d):
        packs = addons.fetch_packs()
        assert [p.id for p in packs] == ["test-milk", "test-toy-nc"], [p.id for p in packs]
        assert not packs[0].noncommercial and packs[1].noncommercial            # by its licence
        assert packs[0].file_url(packs[0].items[0]).endswith("/looks/test-milk/Spin%20one.milk")
    _with_packs(check, extra)
    for bad in (b"not json", b'{"list": 3}'):
        try:
            addons.parse_packs(bad)
            raise AssertionError("read")
        except gallery.GalleryError:
            pass


def test_install_one_look_then_the_rest_then_remove():
    def check(d):
        pk = addons.fetch_packs()[0]
        assert addons.state(pk) == {"Spin one.milk": "", "Spin two.milk": ""}
        assert addons.install(pk, ["Spin one.milk"]) == ["Spin one.milk"]
        assert addons.state(pk) == {"Spin one.milk": "installed", "Spin two.milk": ""}
        here = addons.installed()
        assert list(here) == ["test-milk"] and [i.file for i in here["test-milk"].items] == ["Spin one.milk"]
        addons.install(pk)
        assert set(addons.state(pk).values()) == {"installed"}
        # the gallery's file changes: the one here is an update away
        p = os.path.join(d, "looks", "test-milk", "Spin two.milk")
        with open(p, "ab") as fh:
            fh.write(b"per_frame_2=zoom = zoom + 0.01;\n")
        pk2 = addons.parse_packs(json.dumps({"packs": 1, "list": [dict(pk.as_dict(), items=[
            dict(i.as_dict(), sha256=_sha(open(os.path.join(d, "looks", "test-milk", i.file), "rb").read()))
            for i in pk.items])]}).encode())[0]
        assert addons.state(pk2) == {"Spin one.milk": "installed", "Spin two.milk": "update"}
        addons.install(pk2, ["Spin two.milk"])
        assert addons.state(pk2)["Spin two.milk"] == "installed"
        # one look off, then the last: the pack goes with it
        assert addons.remove("test-milk", "Spin one.milk")
        assert [i.file for i in addons.installed()["test-milk"].items] == ["Spin two.milk"]
        assert not addons.remove("test-milk", "../Spin two.milk")
        assert addons.remove("test-milk", "Spin two.milk")
        assert addons.installed() == {} and not os.path.exists(os.path.join(addons.root(), "test-milk"))
        assert not addons.remove("test-milk")
        try:
            addons.remove("../evil")
            raise AssertionError("removed")
        except ValueError:
            pass
    _with_packs(check)


def test_a_file_that_is_not_the_lists_is_refused():
    def check(d):
        pk = addons.fetch_packs()[0]
        with open(os.path.join(d, "looks", "test-milk", "Spin two.milk"), "ab") as fh:
            fh.write(b"tampered\n")
        try:
            addons.install(pk)
            raise AssertionError("installed")
        except gallery.GalleryError as e:
            assert "sha256" in str(e)
        # the one before it kept, the bad one not written
        assert addons.state(pk) == {"Spin one.milk": "installed", "Spin two.milk": ""}
        assert not [f for f in os.listdir(os.path.join(addons.root(), "test-milk")) if f.endswith(".part")]
    _with_packs(check)


def test_installed_looks_reach_the_vj_and_the_browser():
    proj = SimpleNamespace(path=tempfile.mkdtemp(prefix="studio_packs_proj_"))

    def check(d):
        for pk in addons.fetch_packs():
            addons.install(pk)
        os.makedirs(vj_looks.user_dir(proj), exist_ok=True)
        with open(os.path.join(vj_looks.user_dir(proj), "Mine.milk"), "w") as fh:
            fh.write(MILK)
        errs = vj_looks.load_user(proj, allow_py=False)
        assert not errs, errs
        names = {n: vj_looks.look_source(n) for n in vj_looks.LOOKS if n not in vj_looks.BUILTIN}
        assert names.get("Milk: Mine") == ("project", None), names
        assert names.get("Milk: Spin one") == ("addon", "test-milk"), names
        toy = [n for n, s in names.items() if s == ("addon", "test-toy-nc")]
        assert len(toy) == 1, names
        assert vj_looks.look_source(vj_looks.BUILTIN[0]) == ("builtin", None)
        assert addons.pack_of(vj_looks.look_path("Milk: Spin one")) == "test-milk"

        app = SimpleNamespace(prefs={})
        assert vj.toggle_favourite(app, "Milk: Spin two") and vj.favourites(app) == ["Milk: Spin two"]
        assert json.load(open(project.STUDIO_FILE))["ui"]["vj_favourites"] == ["Milk: Spin two"]
        from native import vj_ui
        sec = dict(vj_ui.browse_sections(app, "favourites"))
        assert list(sec.values()) == [["Milk: Spin two"]], sec
        sec = dict(vj_ui.browse_sections(app, "all add-on packs"))
        assert set(sec) == {"Test: milk", "Test: toys  (non-commercial)"}, sec
        assert dict(vj_ui.browse_sections(app, "pack: Test: toys")) == {"Test: toys  (non-commercial)": toy}
        assert dict(vj_ui.browse_sections(app, "the project's own")) == {"The project's own": ["Milk: Mine"]}
        assert dict(vj_ui.browse_sections(app, "all looks", "spin one")) == {"Test: milk": ["Milk: Spin one"]}
        assert not vj.toggle_favourite(app, "Milk: Spin two") and vj.favourites(app) == []
        # a pack removed: its looks leave the VJ
        addons.remove("test-milk")
        vj_looks.load_user(proj, allow_py=False)
        assert "Milk: Spin one" not in vj_looks.LOOKS and "Milk: Mine" in vj_looks.LOOKS
    try:
        _with_packs(check)
    finally:
        shutil.rmtree(proj.path, ignore_errors=True)
        vj_looks.load_user(proj, allow_py=False)   # the test's looks gone


if __name__ == "__main__":
    import inspect
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print("ok  ", name)
            except Exception as e:
                bad += 1; print("FAIL", name, repr(e)[:2000])
    sys.exit(1 if bad else 0)
