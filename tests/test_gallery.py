"""The shared library online (native/gallery.py), from a gallery on disk
(tests/fake_gallery.py): the index read with what is not whole left out,
an entry's files found by its id alone, a bundle checked against the
index's sha256, the size limits, a preview's frames, and the folder made
for sharing one's own. Run with  python tests/test_gallery.py  (or pytest).
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from native import gallery                              # noqa: E402
import fake_gallery                                      # noqa: E402


def _with_gallery(fn, extra=None):
    d = tempfile.mkdtemp(prefix="studio_gallery_")
    home = tempfile.mkdtemp(prefix="studio_gallery_home_")
    old_url, old_home = os.environ.get("STUDIO_GALLERY_URL"), gallery.paths.HOME
    try:
        os.environ["STUDIO_GALLERY_URL"] = fake_gallery.make(d, extra)
        gallery.paths.HOME = home
        fn(d)
    finally:
        if old_url is None:
            os.environ.pop("STUDIO_GALLERY_URL", None)
        else:
            os.environ["STUDIO_GALLERY_URL"] = old_url
        gallery.paths.HOME = old_home
        shutil.rmtree(d, ignore_errors=True); shutil.rmtree(home, ignore_errors=True)


def test_the_index_keeps_only_whole_entries():
    good = "a" * 64
    extra = [{"id": "../../evil", "sha256": good}, {"id": "Upper", "sha256": good}, {"id": "spirals", "sha256": good},
             {"id": "no-hash"}, {"id": "ok-one", "sha256": good, "name": "x" * 500, "tags": ["t\x00ag", 5]}, "nonsense"]

    def check(d):
        idx = gallery.fetch_index()
        assert [e.id for e in idx] == ["spirals", "fireworks", "ok-one"], [e.id for e in idx]
        last = idx[-1]
        assert len(last.name) == 60 and last.tags == ["t ag"]
        assert last.bundle_url().endswith("/effects/ok-one.graph.json")       # by its id alone
    _with_gallery(check, extra)
    for bad in (b"not json", b'{"entries": 3}'):
        try:
            gallery.parse_index(bad)
            raise AssertionError("read")
        except gallery.GalleryError:
            pass


def test_a_bundle_is_the_one_the_index_names():
    def check(d):
        idx = {e.id: e for e in gallery.fetch_index()}
        path = gallery.fetch_bundle(idx["spirals"])
        assert json.load(open(path, encoding="utf-8"))["graph"]["name"] == "Spirals (gallery)"
        with open(os.path.join(d, "effects", "fireworks.graph.json"), "ab") as f:
            f.write(b" ")                                    # changed after the index was made
        try:
            gallery.fetch_bundle(idx["fireworks"])
            raise AssertionError("a bundle whose sha256 differs was used")
        except gallery.GalleryError as e:
            assert "sha256 differs" in str(e)
        frames = gallery.fetch_preview(idx["spirals"], size=24)
        assert frames and frames[0].shape == (24, 24, 3) and len(frames) == 4
        assert os.path.exists(os.path.join(gallery.cache_dir(), "spirals.gif"))       # kept for next time
    _with_gallery(check)


def test_a_file_past_its_size_is_refused():
    def check(d):
        big = os.path.join(d, "effects", "spirals.graph.json")
        data = b'{"graph": {}, "pad": "' + b"x" * (gallery.BUNDLE_MAX + 10) + b'"}'
        open(big, "wb").write(data)
        e = gallery.Entry({"id": "spirals", "sha256": hashlib.sha256(data).hexdigest()})
        try:
            gallery.fetch_bundle(e)
            raise AssertionError("a bundle past the limit was read")
        except gallery.GalleryError as ex:
            assert "larger than" in str(ex)
    _with_gallery(check)


def test_the_folder_to_share():
    d = tempfile.mkdtemp(prefix="studio_share_")
    old = gallery.paths.CAPTURES
    try:
        gallery.paths.CAPTURES = d
        b = os.path.join(d, "b.graph.json")
        open(b, "wb").write(b'{"studio_graph": 1, "graph": {"name": "Mine"}, "requires": ["audio"]}')
        g = os.path.join(d, "p.gif")
        open(g, "wb").write(b"GIF89a....")
        out = gallery.prepare_share(b, g, "My Aurora!", "me", "A ribbon.", ["2-D"])
        assert out.endswith(os.path.join("gallery-share", "my-aurora"))
        entry = json.load(open(os.path.join(out, "entry.json"), encoding="utf-8"))
        assert entry["id"] == "my-aurora" and entry["requires"] == ["audio"]
        assert entry["sha256"] == hashlib.sha256(open(os.path.join(out, "effects", "my-aurora.graph.json"), "rb").read()).hexdigest()
        assert os.path.exists(os.path.join(out, "previews", "my-aurora.gif"))
    finally:
        gallery.paths.CAPTURES = old
        shutil.rmtree(d, ignore_errors=True)


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
