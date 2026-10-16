"""Recording the views - a mixin of App (app.py): a GIF or an mp4 of what is shown, frame by frame on the main
loop at REC_FPS (catching up when the frame rate is under it), encoded on a worker; and a screenshot of the
view on the next frame."""
import os
import subprocess
import time

import numpy as np

from native import gif, procs
from native import paths as _paths

# Recordings go in captures/ beside the app (paths.CAPTURES), not in the scratch
# folder the remote control lives in. The two are different kinds of file:
# capture.request and crash.txt are scratch that nobody minds losing, whereas a
# recording is a thing you made and meant to keep, and Windows is entitled to
# empty %TEMP% whenever it likes. In a checkout the folder is gitignored.
GIF_DIR = _paths.CAPTURES


class Recorder:
    # --- recording ------------------------------------------------------------
    REC_FPS = 15

    def start_rec(self, secs=15.0, fmt="gif"):
        """A recording of the views for `secs`: a GIF, or an mp4 (fmt "mp4",
        which needs ffmpeg on the path)."""
        if self.rec is not None:
            return
        if fmt == "mp4" and not self.has_ffmpeg():
            self.rec_msg = "a video needs ffmpeg on the path - not found"
            self.gp.status(self.rec_msg); return
        self.rec = []
        self.rec_fmt = fmt
        self.rec_left = secs
        self.rec_next = time.perf_counter()
        self.rec_msg = f"recording {secs:.0f} s ({fmt})..."

    @staticmethod
    def has_ffmpeg():
        import shutil
        return bool(shutil.which("ffmpeg"))

    def _encode(self, frames, path, fmt="gif"):
        """Runs on a worker thread: encoding 225 frames takes several seconds
        and the window must keep drawing while it does. A GIF by the studio's
        own writer; an mp4 by ffmpeg (a GIF of a minute is huge, an mp4 is not)."""
        try:
            if fmt == "mp4":
                if self.write_video(frames, path):
                    self.rec_msg = f"{os.path.basename(path)}  {os.path.getsize(path)/1024:.0f} KB"
                return
            n = gif.write(path, frames, fps=self.REC_FPS)
            self.rec_msg = f"{os.path.basename(path)}  {n/1024:.0f} KB"
        except Exception as e:
            self.rec_msg = f"{fmt} failed: {e}"

    def write_video(self, frames, path, fps=None):
        """The frames as an mp4 through ffmpeg (raw RGB piped in, H.264 out,
        yuv420p so anything plays it). None without ffmpeg on the path."""
        import shutil
        ff = shutil.which("ffmpeg")
        if not ff or not frames:
            return None
        h, w = frames[0].shape[:2]
        w2, h2 = w - w % 2, h - h % 2                     # yuv420p wants even sides
        cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w2}x{h2}",
               "-r", str(fps or self.REC_FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", path]
        try:
            proc = procs.popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            for f in frames:
                proc.stdin.write(np.ascontiguousarray(f[:h2, :w2, :3]).tobytes())
            proc.stdin.close()
            err = proc.stderr.read().decode("utf-8", "replace")
            if proc.wait() != 0:
                self.rec_msg = f"ffmpeg: {err.strip()[-120:]}"; return None
            return path
        except Exception as e:
            self.rec_msg = f"video failed: {e}"; return None

    def _rec_fit(self, frame):
        """A recorded frame at the recording's first size: the window resized or a view turned on or off changed
        it, and the GIF writer raised on the mix (the recording lost) while the mp4 got short rows (garbage,
        said to be done). Another size is centred on a canvas of the first, cut where larger."""
        if not self.rec:
            return frame.copy()
        h0, w0 = self.rec[0].shape[:2]
        if frame.shape[:2] == (h0, w0):
            return frame.copy()
        out = np.zeros((h0, w0, 3), np.uint8)
        h, w = min(h0, frame.shape[0]), min(w0, frame.shape[1])
        oy, ox = (h0 - h) // 2, (w0 - w) // 2
        fy, fx = (frame.shape[0] - h) // 2, (frame.shape[1] - w) // 2
        out[oy:oy + h, ox:ox + w] = frame[fy:fy + h, fx:fx + w, :3]
        return out

    def rec_frame(self, net_img, cube_img):
        """Offered every drawn frame; takes one only when the clock says so."""
        if self.shot_req:
            self.shot_req = False
            img = cube_img if cube_img is not None else net_img
            if img is not None:
                try:
                    from PIL import Image
                    d = os.path.join(self.project.path, "export", "shots")
                    os.makedirs(d, exist_ok=True)
                    name = "".join(c if c.isalnum() else "_" for c in self.eng.names[self.eng.idx])
                    path = os.path.join(d, f"{name}_{int(time.time())}.png")
                    Image.fromarray(np.ascontiguousarray(img)).save(path)
                    self.rec_msg = f"saved {os.path.relpath(path, self.project.path)}"
                except Exception as e:
                    self.rec_msg = f"screenshot failed: {e}"
        if self.rec is None:
            return
        now = time.perf_counter()
        if now < self.rec_next:
            return
        # behind the clock (a frame rate under REC_FPS): the frame taken now stands for the ones missed, so the
        # file's time is the clock's - it played fast and ended early, and a sequence's render froze on its end
        k = 1 + max(0, int((now - self.rec_next) * self.REC_FPS))
        self.rec_next += k / self.REC_FPS
        parts = [p for p in (net_img, cube_img) if p is not None]
        if not parts:
            # nothing drawn to record (both views hidden or popped out): it waited for ever, and no other could start
            self.rec = None
            self.rec_msg = "recording stopped: no view is showing - show the net or the 3-D view"
            return
        if len(parts) == 1:
            frame = parts[0]
        else:
            h = max(p.shape[0] for p in parts)
            frame = np.zeros((h, sum(p.shape[1] for p in parts) + 8, 3), np.uint8)
            x = 0
            for p in parts:
                y = (h - p.shape[0]) // 2
                frame[y:y + p.shape[0], x:x + p.shape[1]] = p
                x += p.shape[1] + 8
        frame = self._rec_fit(frame)
        self.rec.extend([frame] * k)
        self.rec_left -= k / self.REC_FPS
        if self.rec_left > 0:
            self.rec_msg = f"recording {self.rec_left:4.1f} s..."
            return
        frames, self.rec = self.rec, None
        fmt = getattr(self, "rec_fmt", "gif")
        name = "".join(c if c.isalnum() else "_" for c in self.eng.names[self.eng.idx])
        os.makedirs(GIF_DIR, exist_ok=True)
        path = os.path.join(GIF_DIR, f"{name}_{int(time.time())}.{fmt}")
        self.rec_msg = f"encoding {len(frames)} frames ({fmt})..."
        import threading
        threading.Thread(target=self._encode, args=(frames, path, fmt), daemon=True).start()
