"""Report a problem: everything a bug report needs, in one zip.

    path = bundle(app)      -> captures/report_<day>_<time>.zip

What goes in: what this build is (version.json, or the version and the
git commit from a checkout), the doctor's findings, the machine (OS,
Python, the display), the project's name, geometry and options with the
device names blanked, the prefs, the last crash tracebacks (crash.txt
and crash.prev.txt from the scratch folder), the engine build's latest
name, and the last lines the app printed (when the console variant is
running). No captures, no effects, no graphs: nothing of the user's
work - a report is about the studio.
"""
import json
import os
import platform
import sys
import time
import zipfile

from native import paths, version


def _what_build():
    p = os.path.join(paths.HOME, "version.json")
    if not os.path.exists(p):
        p = os.path.join(paths.RES, "version.json")
    if os.path.exists(p):
        try:
            return open(p, encoding="utf-8").read()
        except OSError:
            pass
    commit = ""
    try:
        import subprocess
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=paths.RES, timeout=5).stdout.strip()
    except Exception:
        pass
    return json.dumps({"version": version.__version__, "commit": commit, "built": "a checkout"}, indent=1)


def _doctor():
    try:
        from native.doctor import check
        return "\n".join(f"{'ok  ' if ok else ('--  ' if ok is None else 'MISSING')}  {line}" + (f"\n        -> {fix}" if fix else "")
                         for ok, line, fix in check())
    except Exception as e:
        return f"the doctor could not run: {e}"


def _machine(app):
    d = {"os": platform.platform(), "python": sys.version.split()[0], "frozen": paths.FROZEN,
         "home": paths.HOME, "resources": paths.RES, "tree": paths.TREE}
    if app is not None:                                   # the viewport is only asked with the app up: without a context it faults
        try:
            import dearpygui.dearpygui as dpg
            d["dearpygui"] = dpg.get_dearpygui_version()
            d["viewport"] = [dpg.get_viewport_client_width(), dpg.get_viewport_client_height()]
        except Exception:
            pass
        try:
            d["engine"] = os.path.basename(app.eng.library or "")
            d["effects"] = len(app.eng.names)
            d["effect"] = app.eng.names[app.eng.idx] if app.eng.names else ""
            d["layout"] = app.layout
            d["gpu"] = bool(getattr(app, "cube_quads", None) or getattr(app, "point_quads", None))
        except Exception:
            pass
    return json.dumps(d, indent=1)


def _project(app):
    if app is None:
        return "{}"
    p = app.project
    opts = json.loads(json.dumps(p.options))
    for k in ("device", "devices"):                       # no addresses of the user's network
        if k in opts:
            opts[k] = "(blanked)"
    return json.dumps({"name": os.path.basename(p.path), "geometry": p.geometry.to_json(), "imported": p.imported,
                       "options": opts, "effects": sorted(p.effect_files())}, indent=1)


def bundle(app=None, log_lines=()):
    """The zip, in captures/. Returns its path."""
    os.makedirs(paths.CAPTURES, exist_ok=True)
    path = os.path.join(paths.CAPTURES, time.strftime("report_%Y%m%d_%H%M%S.zip"))
    scratch = os.path.join(__import__("tempfile").gettempdir(), "cubefx")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("version.json", _what_build())
        z.writestr("doctor.txt", _doctor())
        z.writestr("machine.json", _machine(app))
        z.writestr("project.json", _project(app))
        prefs = os.path.join(paths.PROJECTS, "studio.json")
        if os.path.exists(prefs):
            z.write(prefs, "studio.json")
        for name in ("crash.txt", "crash.prev.txt"):
            p = os.path.join(scratch, name)
            if os.path.exists(p):
                z.write(p, name)
        latest = os.path.join(paths.BUILD, "latest")
        if os.path.exists(latest):
            z.write(latest, "build_latest.txt")
        if log_lines:
            z.writestr("log.txt", "\n".join(log_lines))
        z.writestr("README.txt", f"A problem report from WLED Effects Studio {version.__version__}.\n"
                                 f"Attach this zip to an issue at https://github.com/{version.REPO}/issues and say what you did, "
                                 "what you expected and what happened.\nIt holds: what this build is, the doctor's findings, "
                                 "the machine, the project's settings (device addresses blanked), the prefs, the last crash "
                                 "tracebacks - nothing of your effects, graphs or captures.\n")
    return path
