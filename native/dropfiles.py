"""Files dropped on the window from the desktop.

Dear PyGui takes no drops itself, but on Windows its viewport is an ordinary
window: DragAcceptFiles() on it and a window procedure of our own in front
of Dear PyGui's, answering WM_DROPFILES and passing everything else on. The
paths are queued; the app's loop takes them on its own thread and decides
what each one is (a graph, a code effect, an image, an XYZ file, a ledmap).

    drop = DropFiles("WLED Effects Studio")     # after show_viewport()
    for path in drop.take(): ...                # each loop pass

Elsewhere (macOS, Linux) this does nothing and says so once; the imports on
the File menu cover it.
"""
import os
import sys
import threading

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


class DropFiles:
    def __init__(self, title):
        self.paths = []
        self._lock = threading.Lock()
        self.ok = False
        self._proc = None
        self._old = None
        if sys.platform != "win32":
            return
        try:
            self._install(title)
        except Exception as e:                      # a missing DLL, an odd window: no drops, no crash
            self.error = str(e)

    def _install(self, title):
        import ctypes
        from ctypes import wintypes
        u32, s32 = ctypes.windll.user32, ctypes.windll.shell32
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            raise RuntimeError("viewport window not found")
        s32.DragAcceptFiles(hwnd, True)
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
        u32.SetWindowLongPtrW.restype = ctypes.c_longlong
        u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        u32.CallWindowProcW.restype = ctypes.c_longlong
        u32.CallWindowProcW.argtypes = [ctypes.c_longlong, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
        s32.DragQueryFileW.argtypes = [wintypes.HANDLE, ctypes.c_uint, wintypes.LPWSTR, ctypes.c_uint]
        s32.DragFinish.argtypes = [wintypes.HANDLE]

        def proc(h, msg, wp, lp):
            if msg == WM_DROPFILES:
                try:
                    n = s32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                    got = []
                    for i in range(n):
                        buf = ctypes.create_unicode_buffer(1024)
                        s32.DragQueryFileW(wp, i, buf, 1024)
                        got.append(buf.value)
                    s32.DragFinish(wp)
                    with self._lock:
                        self.paths.extend(got)
                except Exception:
                    pass
                return 0
            return u32.CallWindowProcW(self._old, h, msg, wp, lp)

        self._proc = WNDPROC(proc)                  # kept: the window calls it for as long as it lives
        self._old = u32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p).value)
        self.ok = bool(self._old)

    def take(self):
        with self._lock:
            out, self.paths = self.paths, []
        return out


def classify(path):
    """What a dropped file is, by its name and a look inside: graph, code,
    image, xyz, ledmap, wav, or None."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cpp":
        return "code"
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
        return "image"
    if ext == ".wav":
        return "wav"
    if ext in (".csv", ".txt", ".xyz"):
        return "xyz"
    if ext == ".json":
        try:
            import json
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            return None
        if isinstance(d, dict) and "map" in d:
            return "ledmap"
        if isinstance(d, dict) and ("nodes" in d or "graph" in d):
            return "graph"
        if isinstance(d, list):
            return "xyz"
    return None
