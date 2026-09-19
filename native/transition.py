"""WLED's transition styles, for the sim: the old effect's picture and
the new one's blended by a progress 0..1 the way the device blends them
at an effect change (FX_fcn.cpp: fade, swipes, pushes, outside-in and
inside-out, circular, fairy dust). The device does this with the
segments' own buffers; here it is done on the two pictures, which is the
same thing for the eye.

    frame = blend(old_rgb, new_rgb, progress, "swipe right")   # (rows, cols, 3) uint8
"""
import numpy as np

STYLES = ["fade", "swipe right", "swipe left", "swipe up", "swipe down", "push right", "push left", "push up", "push down",
          "outside in", "inside out", "circular in", "circular out", "fairy dust"]
# WLED's blend-style ids (FX.h TRANSITION_*), for a device whose setting the sequence should match
WLED_IDS = {"fade": 0, "swipe right": 2, "swipe left": 3, "swipe up": 6, "swipe down": 7, "push right": 16, "push left": 17,
            "push up": 18, "push down": 19, "outside in": 8, "inside out": 9, "circular in": 14, "circular out": 15, "fairy dust": 1}


def blend(old, new, prog, style="fade"):
    old = np.asarray(old, np.uint8); new = np.asarray(new, np.uint8)
    if old.shape != new.shape:
        return new
    p = float(max(0.0, min(1.0, prog)))
    h, w = new.shape[:2]
    if style == "fade" or w * h == 1:
        return (old.astype(np.float32) * (1 - p) + new.astype(np.float32) * p).astype(np.uint8)
    ys, xs = np.mgrid[0:h, 0:w]
    if style == "swipe right":
        m = xs < p * w
    elif style == "swipe left":
        m = xs >= (1 - p) * w
    elif style == "swipe down":
        m = ys < p * h
    elif style == "swipe up":
        m = ys >= (1 - p) * h
    elif style.startswith("push"):
        # both move: the new one slides in, pushing the old one out
        d = int(round(p * (w if style in ("push right", "push left") else h)))
        out = old.copy()
        if style == "push right":
            out[:, d:] = old[:, :w - d] if d < w else old[:, :0]
            out[:, :d] = new[:, w - d:]
        elif style == "push left":
            out[:, :w - d] = old[:, d:]
            out[:, w - d:] = new[:, :d]
        elif style == "push down":
            out[d:, :] = old[:h - d, :]
            out[:d, :] = new[h - d:, :]
        else:
            out[:h - d, :] = old[d:, :]
            out[h - d:, :] = new[:d, :]
        return out
    elif style == "outside in":
        dw, dh = (1 - p) * w / 2, (1 - p) * h / 2
        m = ~((xs >= dw) & (xs < w - dw) & (ys >= dh) & (ys < h - dh))
    elif style == "inside out":
        dw, dh = p * w / 2, p * h / 2
        m = (xs >= w / 2 - dw) & (xs < w / 2 + dw) & (ys >= h / 2 - dh) & (ys < h / 2 + dh)
    elif style in ("circular in", "circular out"):
        cx, cy = (w - 1) / 2, (h - 1) / 2
        r = np.hypot(xs - cx, ys - cy)
        R = np.hypot(cx + 1, cy + 1)
        m = r <= p * R if style == "circular out" else r >= (1 - p) * R
    elif style == "fairy dust":
        rnd = ((xs * 73856093) ^ (ys * 19349663)) % 1000 / 1000.0          # a fixed scatter: the same pixels turn first every time
        m = rnd < p
    else:
        return new
    return np.where(m[..., None], new, old)
