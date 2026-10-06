"""Window > Effect slots...: the active device's effect bank (bank.py) -
which compiled cube_fx effects take one of its slots, in what order - read
from the device, changed here, and written back with the reboot that
applies it. So a newly flashed effect reaches the cube's own effect list
(and the on-cube menu) without opening the device's settings page.

    build(app)   # the window (chrome.build calls it)
    show(app)    # open it (the device is read when asked: Read the device)
    poll(app)    # per frame: a read or a write finished on its thread

The left list is what the studio's firmware build compiles (the cube_fx
effects in the sim); the right, the slots in order. A slot the device holds
for an effect this build cannot name is left out of the list (the window
says how many) and so is dropped by a write. The network work runs on a
thread; the window shows "reading..." or "writing..." meanwhile.
"""
import threading

import dearpygui.dearpygui as dpg

from native.typeface import px
from native import typeface, weight, bank

TAG = "bank_win"


def _c():
    from native import chrome
    return chrome


def candidates(app):
    """The effects the firmware compiles that a slot can hold, in the sim's own spelling and order."""
    from native import library_ui
    um = library_ui.usermod_names()
    return [n for n in app.eng.names if n.strip().lower() in um]


def build(app):
    c = _c()
    app._bank = {"slots": [], "hashes": [], "busy": None, "result": None, "status": ""}
    with dpg.window(tag=TAG, label="Effect slots", no_title_bar=True, show=False, width=px(640), height=px(560), no_collapse=True):
        c.dialog_header(TAG, "Effect slots")
        dpg.add_text("", tag="bank_note", color=c.DIM, wrap=px(620))
        with dpg.group(horizontal=True):
            dpg.add_text("", tag="bank_dev", color=c.TEXT)
            dpg.add_button(label="Read the device", tag="bank_read", small=True, callback=lambda: read(app))
            weight.need(dpg.last_item(), "device")
            c.tip("the device's slots and what it says of them, read again")
        dpg.add_text("", tag="bank_state", color=c.DIM, wrap=px(620))
        with dpg.group(horizontal=True):
            with dpg.group():
                typeface.label(dpg.add_text("COMPILED", color=c.ACCENT))
                dpg.add_listbox([], tag="bank_avail", num_items=14, width=px(260))
                c.tip("the cube_fx effects in the studio's firmware build - flash it first for one the device does not have")
            with dpg.group():
                dpg.add_spacer(height=px(40))
                dpg.add_button(label="Add", tag="bank_add", width=px(80), callback=lambda: add(app))
                c.tip("the selected effect onto the end of the slots")
                dpg.add_button(label="Add the rest", tag="bank_add_all", width=px(80), callback=lambda: add_rest(app))
                c.tip("every compiled effect not in a slot yet, in the list's order, while slots last")
                dpg.add_spacer(height=px(10))
                dpg.add_button(label="Up", tag="bank_up", width=px(80), callback=lambda: move(app, -1))
                c.tip("the selected slot one place earlier: earlier slots come first in the device's effect list")
                dpg.add_button(label="Down", tag="bank_down", width=px(80), callback=lambda: move(app, 1))
                dpg.add_button(label="Remove", tag="bank_rm", width=px(80), callback=lambda: remove(app))
                weight.danger(dpg.last_item())
                c.tip("the selected effect out of the slots: it stays compiled, but off the device's list")
            with dpg.group():
                typeface.label(dpg.add_text("", tag="bank_slots_lab", color=c.ACCENT))
                dpg.add_listbox([], tag="bank_slots", num_items=14, width=px(260))
                c.tip("the device's effect list after the built-ins, in this order, from the next boot")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Write to the device and reboot", tag="bank_write", callback=lambda: write(app))
            weight.primary(dpg.last_item())
            weight.need(dpg.last_item(), "device")
            c.tip("the slots into the device's settings (the rest of them kept), then a reboot - effects join the list at "
                  "boot. The device is dark for a few seconds")
            dpg.add_text("", tag="bank_msg", color=c.DIM, wrap=px(380))


def show(app):
    """Open it. The device is not read until asked: a window opened by the menu walk must not reach out to
    whatever device the walked project names (a real one, on the developer's network)."""
    _c()._centre(TAG, 640, 560)
    dpg.show_item(TAG)
    b = app._bank
    if not b["busy"] and not b["status"]:
        b["status"] = "Read the device to see its slots."
    refresh(app)


def _n_slots(app):
    return max(len(app._bank["hashes"]), bank.SLOTS)


def refresh(app):
    if not dpg.does_item_exist(TAG):
        return
    b = app._bank
    host = app.active_host()
    dpg.set_value("bank_dev", f"device: {host}" if host else "device: none chosen - Window > Devices...")
    dpg.set_value("bank_note", "Which cube_fx effects get one of the device's effect slots, and in what order: the device "
                               "lists only these (after its built-ins), and the order is the list's. Changes apply when it "
                               "reboots.")
    taken = set(b["slots"])
    dpg.configure_item("bank_avail", items=[n for n in candidates(app) if n not in taken])
    items = [f"{k + 1}. {n}" for k, n in enumerate(b["slots"])]
    keep = dpg.get_value("bank_slots")
    dpg.configure_item("bank_slots", items=items)
    if items:
        dpg.set_value("bank_slots", keep if keep in items else items[0])
    dpg.set_value("bank_slots_lab", f"SLOTS  {len(b['slots'])} of {_n_slots(app)}")
    busy = b["busy"]
    dpg.set_value("bank_state", {"read": "reading the device...", "write": "writing the slots..."}.get(busy, b["status"]))
    for t in ("bank_write", "bank_read"):
        dpg.configure_item(t, enabled=busy is None)


def _sel(app):
    v = dpg.get_value("bank_slots")
    try:
        return int(str(v).split(".", 1)[0]) - 1
    except (TypeError, ValueError):
        return -1


def add(app, name=None):
    b = app._bank
    name = name or dpg.get_value("bank_avail")
    if not name or name in b["slots"]:
        return
    if len(b["slots"]) >= _n_slots(app):
        dpg.set_value("bank_msg", f"every one of the {_n_slots(app)} slots is taken: remove one first"); return
    b["slots"].append(name)
    refresh(app)


def add_rest(app):
    b = app._bank
    for n in candidates(app):
        if len(b["slots"]) >= _n_slots(app):
            break
        if n not in b["slots"]:
            b["slots"].append(n)
    refresh(app)


def move(app, d):
    sl = app._bank["slots"]
    k = _sel(app)
    j = k + d
    if 0 <= k < len(sl) and 0 <= j < len(sl):
        sl[k], sl[j] = sl[j], sl[k]
        refresh(app)
        dpg.set_value("bank_slots", f"{j + 1}. {sl[j]}")


def remove(app):
    sl = app._bank["slots"]
    k = _sel(app)
    if 0 <= k < len(sl):
        sl.pop(k)
        refresh(app)


# --- the network, on a thread ---------------------------------------------------------------
def _run(app, kind, fn):
    b = app._bank
    if b["busy"]:
        return
    b["busy"], b["result"] = kind, None

    def go():
        try:
            b["result"] = (kind, fn())
        except Exception as e:
            b["result"] = (kind, e)
    threading.Thread(target=go, daemon=True).start()
    refresh(app)


def read(app):
    host = app.active_host()
    if not host:
        app._bank["status"] = "no device chosen"; refresh(app); return
    _run(app, "read", lambda: (bank.read(host), bank.status(host)))


def write(app):
    host = app.active_host()
    if not host:
        return
    names = list(app._bank["slots"])
    _run(app, "write", lambda: bank.write(host, names))


def poll(app):
    b = getattr(app, "_bank", None)
    if not b or b["result"] is None:
        return
    kind, res = b["result"]
    b["result"], b["busy"] = None, None
    if isinstance(res, Exception):
        b["status"] = f"the device did not answer: {res}"
    elif kind == "read":
        st, (placed, free) = res
        if st is None:
            b["slots"], b["hashes"] = [], []
            b["status"] = "this device's firmware has no effect bank - flash a cube_fx build first"
        else:
            b["hashes"] = st["slots"]
            named = bank.slot_names(st["slots"], candidates(app))
            other = sum(1 for n in named if n == "?")
            b["slots"] = [n for n in named if n and n != "?"]
            words = placed or ("bank off" if not st["enabled"] else "")
            if not any(st["slots"]):
                words = "no slots chosen: the device registers every compiled effect it has room for" + (f" ({placed})" if placed else "")
            b["status"] = words + (f"; {other} slot(s) hold an effect this build does not have - dropped if written" if other else "")
    else:
        ok, msg = res
        b["status"] = msg
        app.gp.status(f"effect slots: {msg}", "info" if ok else "warn")
        if ok:
            # the device's effect list changes with the reboot: MIDI's lookups start again
            sw = getattr(app, "devfx", None)
            if sw is not None:
                sw._names.clear()
    refresh(app)
