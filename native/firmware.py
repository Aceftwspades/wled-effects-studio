"""Firmware other than the studio's own build, for the Flash frame: WLED's
official release binaries (read from its GitHub releases, downloaded once
into HOME/firmware), and a .bin someone already has - and, for any of them
and the studio's build alike, what chip a binary is for, so a firmware for
another chip is never sent (a device takes it, and does not boot).

    rels = releases()                          # newest first: [{"tag", "name", "pre", "date", "assets"}]
    a = assets_for(rels[0], "esp32-s3")        # its files for this chip, the plainest first
    path = download(rels[0]["tag"], a[0])      # cached; progress(done, total) as it comes
    bin_chip(path)                             # "esp32-s3" - read from the image's header

STUDIO_WLED_RELEASES_URL points the list at another releases JSON (a test's).
"""
import json
import os
import struct
import urllib.parse
import urllib.request

from native import paths

RELEASES_URL = "https://api.github.com/repos/wled/WLED/releases?per_page=20"
CACHE = os.path.join(paths.HOME, "firmware")
TIMEOUT = 10

# the chips WLED is built for, as a device's /json/info "arch" names them (lower case, a dash)
CHIPS = ("esp8266", "esp32", "esp32-s2", "esp32-s3", "esp32-c3", "esp32-c6")
# esp_image_header_t's chip_id (offset 12), ESP-IDF's esp_chip_id_t
_CHIP_IDS = {0: "esp32", 2: "esp32-s2", 5: "esp32-c3", 9: "esp32-s3", 12: "esp32-c2", 13: "esp32-c6", 16: "esp32-h2"}


def chip(arch):
    """A device's arch (or a board's, a file name's) as one of CHIPS: "ESP32-S3" -> "esp32-s3"."""
    a = str(arch or "").lower().replace("_", "-")
    for c in ("esp32-s3", "esp32-s2", "esp32-c3", "esp32-c6"):
        if c in a or c.replace("-", "") in a.replace("-", ""):
            return c
    if "8266" in a or "esp01" in a or "esp02" in a:
        return "esp8266"
    if "esp32" in a:
        return "esp32"
    return None


def chip_of_asset(name):
    """The chip a release file is for, from its name (WLED_0.15.0_ESP32-S3_8MB_opi.bin)."""
    n = name.upper()
    for key, c in (("S3", "esp32-s3"), ("S2", "esp32-s2"), ("C3", "esp32-c3"), ("C6", "esp32-c6")):
        if f"ESP32-{key}" in n or f"ESP32{key}" in n or f"_{key}_" in n:
            return c
    if "ESP8266" in n or "ESP01" in n or "ESP02" in n or "8266" in n:
        return "esp8266"
    if "ESP32" in n:
        return "esp32"
    return None


def bin_chip(path):
    """The chip a firmware image is for, read from its header - None when the
    file is not an ESP firmware image at all. A gzipped image (ESP8266's
    .bin.gz) is taken as the ESP8266's."""
    try:
        with open(path, "rb") as f:
            h = f.read(24)
    except OSError:
        return None
    if h[:2] == b"\x1f\x8b":
        return "esp8266"
    if len(h) < 24 or h[0] != 0xE9:
        return None
    entry = struct.unpack_from("<I", h, 4)[0]
    if 0x40100000 <= entry < 0x40110000:                   # the ESP8266's IRAM: its images have no extended header
        return "esp8266"
    return _CHIP_IDS.get(struct.unpack_from("<H", h, 12)[0])


def check(path, arch):
    """(ok, words): whether a firmware may go to a device of this arch."""
    want = chip(arch)
    got = bin_chip(path)
    if got is None:
        return False, f"{os.path.basename(path)} is not an ESP firmware image (no image header)"
    if want and got != want:
        return False, f"{os.path.basename(path)} is for an {got}, the device is an {want} - it would not boot"
    return True, f"an {got} image" + ("" if want else " (the device's chip unknown: not checked against it)")


# --- WLED's releases ------------------------------------------------------------------------
def _cache_file():
    return os.path.join(CACHE, "releases.json")


def releases(force=False):
    """WLED's releases, newest first: [{"tag", "name", "pre", "date", "assets": [{"name", "url", "size"}]}],
    only the firmware files. From GitHub, kept on disk for when it cannot be reached (and for an hour)."""
    import time
    cf = _cache_file()
    if not force and os.path.exists(cf) and time.time() - os.path.getmtime(cf) < 3600:
        try:
            return json.load(open(cf, encoding="utf-8"))
        except Exception:
            pass
    url = os.environ.get("STUDIO_WLED_RELEASES_URL") or RELEASES_URL
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "wled-effects-studio"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        try:
            return json.load(open(cf, encoding="utf-8"))
        except Exception:
            return []
    out = []
    for d in raw if isinstance(raw, list) else []:
        assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "size": int(a.get("size") or 0)}
                  for a in d.get("assets") or [] if str(a.get("name", "")).lower().endswith((".bin", ".bin.gz"))]
        if assets and not d.get("draft"):
            out.append({"tag": d.get("tag_name", ""), "name": d.get("name") or d.get("tag_name", ""), "pre": bool(d.get("prerelease")),
                        "date": str(d.get("published_at") or "")[:10], "assets": assets})
    try:
        os.makedirs(CACHE, exist_ok=True)
        json.dump(out, open(cf, "w", encoding="utf-8"), indent=1)
    except OSError:
        pass
    return out


# what marks a build for one board or a special case, not a chip's plain build: listed after the plain ones
_ODD = ("ETHERNET", "DEBUG", "ESP01", "ESP02", "_V4", "AUDIO", "WROVER", "PSRAM", "_160", "BOOTLOADER", "HUB75", "HD-WF2",
        "MATRIXPORTAL", "WAVESHARE", "WROOM", "QIO", "COMPAT", "_MIN", "_NONE")


def assets_for(rel, arch):
    """A release's files for this chip, the plainest first (no Ethernet, debug or board variant)."""
    c = chip(arch)
    files = [a for a in (rel or {}).get("assets") or [] if c is None or chip_of_asset(a["name"]) == c]
    return sorted(files, key=lambda a: (sum(k in a["name"].upper() for k in _ODD), len(a["name"]), a["name"]))


def download(tag, asset, progress=None):
    """A release file into HOME/firmware/<tag>/ (once); its path."""
    d = os.path.join(CACHE, "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(tag)))
    os.makedirs(d, exist_ok=True)
    name = os.path.basename(urllib.parse.urlparse(asset["url"]).path) or asset["name"]
    out = os.path.join(d, name)
    if os.path.exists(out) and (not asset.get("size") or os.path.getsize(out) == asset["size"]):
        return out
    req = urllib.request.Request(asset["url"], headers={"User-Agent": "wled-effects-studio"})
    with urllib.request.urlopen(req, timeout=30) as r, open(out + ".part", "wb") as f:
        total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
        done = 0
        while True:
            b = r.read(65536)
            if not b:
                break
            f.write(b)
            done += len(b)
            if progress:
                progress(done, total)
    os.replace(out + ".part", out)
    return out
