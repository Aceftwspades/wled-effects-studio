"""The studio's scratch folder (native/scratch.py; GHSA-h8r2-jh8g-f2xh): a
folder of this user's alone or none - made 0700, refused when it is a link,
someone else's or open to others - files in it never opened through a link,
and the remote control off unless STUDIO_REMOTE_CONTROL asks for it.
Run with  python tests/test_scratch.py  (or pytest)."""
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from native import scratch


def test_a_folder_of_ones_own_or_none():
    base = tempfile.mkdtemp()
    try:
        d = os.path.join(base, "fresh")
        assert scratch._private(d) and os.path.isdir(d)
        if os.name != "nt":
            assert stat.S_IMODE(os.lstat(d).st_mode) & 0o077 == 0              # made for this user alone
            opened = os.path.join(base, "opened")
            os.mkdir(opened)
            os.chmod(opened, 0o777)                                          # as another user's /tmp/cubefx would be to us
            assert not scratch._private(opened)
            link = os.path.join(base, "link")
            os.symlink(d, link)
            assert not scratch._private(link)                                # a link to somewhere, not a folder
        f = os.path.join(base, "file")
        open(f, "w").close()
        assert not scratch._private(f)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_where_it_is():
    """Windows: the user's own %TEMP%; elsewhere the user's run directory when there
    is one, then a folder named for the user in the temp folder - never a shared name."""
    saved = os.environ.get("XDG_RUNTIME_DIR")
    base = tempfile.mkdtemp()
    try:
        os.environ["XDG_RUNTIME_DIR"] = base
        c = scratch.candidates()
        if os.name == "nt":
            assert c == [os.path.join(tempfile.gettempdir(), "cubefx")]
        else:
            assert c[0] == os.path.join(base, "cubefx")
            assert c[-1] == os.path.join(tempfile.gettempdir(), f"cubefx-{os.getuid()}")
            os.environ["XDG_RUNTIME_DIR"] = os.path.join(base, "not-there")   # not the system's: not made here
            assert len(scratch.candidates()) == 1
    finally:
        if saved is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = saved
        shutil.rmtree(base, ignore_errors=True)


def test_files_are_not_opened_through_a_link():
    base = tempfile.mkdtemp()
    try:
        p = os.path.join(base, "crash.txt")
        scratch.write_text(p, "one\n")
        scratch.write_text(p, "two\n", append=True)
        assert scratch.read_text(p) == "one\ntwo\n"
        if os.name != "nt":
            assert stat.S_IMODE(os.stat(p).st_mode) & 0o077 == 0
        victim = os.path.join(base, "victim.txt")
        open(victim, "w").write("keep me")
        link = os.path.join(base, "command.json")
        try:
            os.symlink(victim, link)
        except (OSError, NotImplementedError):
            return                                                           # Windows without the right to make links
        for write in (lambda: scratch.write_text(link, "x"), lambda: scratch.write_text(link, "x", append=True)):
            try:
                write()
                raise AssertionError("wrote through a link")
            except OSError:
                pass
        try:
            scratch.read_text(link)
            raise AssertionError("read through a link")
        except OSError:
            pass
        assert open(victim).read() == "keep me"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_remote_control_is_asked_for():
    saved = os.environ.get("STUDIO_REMOTE_CONTROL")
    try:
        os.environ.pop("STUDIO_REMOTE_CONTROL", None)
        assert not scratch.remote_control()
        os.environ["STUDIO_REMOTE_CONTROL"] = "0"
        assert not scratch.remote_control()
        os.environ["STUDIO_REMOTE_CONTROL"] = "1"
        assert scratch.remote_control() == (scratch.DIR is not None)
    finally:
        if saved is None:
            os.environ.pop("STUDIO_REMOTE_CONTROL", None)
        else:
            os.environ["STUDIO_REMOTE_CONTROL"] = saved


if __name__ == "__main__":
    bad = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:
                bad += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, e)
    sys.exit(1 if bad else 0)
