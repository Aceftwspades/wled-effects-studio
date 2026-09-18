"""The keymap: every keyboard action, its default key, and the user's own.

An action is a name, a label, a default binding and a context - "global"
(anywhere) or "graph" (the graph pane, where the node keys live). Bindings
are strings like "Ctrl+Shift+S"; the user's are kept in the prefs file
(`studio.json`, under "keys") and only the ones they changed are written,
so a new default reaches everyone who did not rebind it.

    keys = Keymap(prefs)
    keys.lookup("Ctrl+S", "global")   -> "save"
    keys.set("save", "Ctrl+Shift+S")  # unbinds whatever else had it
    keys.label("save")                -> "Ctrl+Shift+S", for a menu
"""
import dearpygui.dearpygui as dpg

# (action, label, default binding, context). The order is the dialog's.
ACTIONS = [
    # views
    ("view_net",      "Logical net, full frame (again: back to the panels)", "Q",      "global"),
    ("view_cube",     "3-D view, full frame (again: back)",                  "E",      "global"),
    ("view_both",     "Net and 3-D, full frame (again: back)",               "W",      "global"),
    ("pane_code",     "Code pane (again: back)",                             "C",      "global"),
    ("pane_graph",    "Graph pane (again: back)",                            "G",      "global"),
    ("presentation",  "Presentation: hide / show the controls",              "H",      "global"),
    ("fullscreen",    "Fullscreen window",                                   "F11",    "global"),
    ("side_panel",    "Hide / show the side panel",                          "Ctrl+Shift+H", "global"),
    ("props_pane",    "Hide / show the graph's properties pane",             "N",      "graph"),
    # playback
    ("play_pause",    "Play / pause",                                        "Space",  "global"),
    ("step",          "Step one frame",                                      ".",      "global"),
    ("restart",       "Restart the effect",                                  "Ctrl+R", "global"),
    ("prev_effect",   "Previous effect in the list",                         "[",      "global"),
    ("next_effect",   "Next effect in the list",                             "]",      "global"),
    ("prev_palette",  "Previous palette",                                    "Shift+[", "global"),
    ("next_palette",  "Next palette",                                        "Shift+]", "global"),
    ("live",          "Live: rebuild the graph as it changes",               "L",      "global"),
    ("compare",       "Compare with another effect side by side / stop",     "Ctrl+Shift+B", "global"),
    ("sweep",         "Sweep a slider through its range / stop",             "Ctrl+Shift+W", "global"),
    ("build",         "Compile + reload",                                    "F5",     "global"),
    # files
    ("new",           "New effect",                                          "Ctrl+N", "global"),
    ("open",          "Open a graph or code effect (the list)",              "Ctrl+O", "global"),
    ("save",          "Save",                                                "Ctrl+S", "global"),
    ("rename",        "Rename",                                              "F2",     "global"),
    ("import",        "Add to / remove from the effects list",               "Ctrl+I", "global"),
    ("find",          "Find / replace in the code",                          "Ctrl+F", "global"),
    ("find_next",     "Find the next match",                                 "F3",     "global"),
    ("find_prev",     "Find the previous match",                             "Shift+F3", "global"),
    ("external",      "Open the code in the external editor",                "Ctrl+E", "global"),
    ("screenshot",    "Screenshot of the 3-D view",                          "F12",    "global"),
    ("record",        "Record a 15 s GIF",                                   "Ctrl+F12", "global"),
    ("shortcuts",     "Keyboard shortcuts",                                  "F1",     "global"),
    ("flash",         "Build the firmware and flash the device",             "Ctrl+Shift+U", "global"),
    ("push",          "Send the current effect's settings to the device",     "Ctrl+Shift+P", "global"),
    ("script_preview", "Run the graph as a script (what the device would run)", "Ctrl+Shift+R", "global"),
    ("script_send",   "Send the graph to the device as a script",             "Ctrl+Shift+D", "global"),
    # the graph
    ("undo",          "Undo (the graph, or the code)",                       "Ctrl+Z", "global"),
    ("redo",          "Redo (the graph, or the code)",                       "Ctrl+Y", "global"),
    ("cut",           "Cut",                                                 "Ctrl+X", "graph"),
    ("copy",          "Copy",                                                "Ctrl+C", "graph"),
    ("paste",         "Paste",                                               "Ctrl+V", "graph"),
    ("duplicate",     "Duplicate with its inputs",                           "Shift+D", "graph"),
    ("delete",        "Delete the selection",                                "Delete", "graph"),
    ("add_node",      "Add a node (search)",                                 "Shift+A", "graph"),
    ("connect",       "Connect two selected nodes",                          "F",      "graph"),
    ("mute",          "Mute",                                                "M",      "graph"),
    ("collapse",      "Collapse / expand",                                   "K",      "graph"),
    ("hide_pins",     "Hide / show unwired pins",                            "Ctrl+H", "graph"),
    ("fold",          "Fold the selection into a sub-graph",                 "Ctrl+G", "graph"),
    ("enter_sub",     "Enter the selected sub-graph / back out",             "Tab",    "graph"),
    ("arrange",       "Arrange (the selection, or the whole graph)",         "Ctrl+L", "graph"),
    ("align_left",    "Align the selected nodes' left edges",                "Alt+Left", "graph"),
    ("align_right",   "Align their right edges",                             "Alt+Right", "graph"),
    ("align_top",     "Align their tops",                                    "Alt+Up", "graph"),
    ("align_bottom",  "Align their bottoms",                                 "Alt+Down", "graph"),
    ("distribute_x",  "Distribute the selected nodes across",                "Alt+H", "graph"),
    ("distribute_y",  "Distribute them down",                                "Alt+V", "graph"),
    ("zoom_in",       "Zoom in",                                             "Ctrl+=", "graph"),
    ("zoom_out",      "Zoom out",                                            "Ctrl+-", "graph"),
    ("zoom_reset",    "Zoom 100%",                                           "Ctrl+0", "graph"),
    ("frame_all",     "Frame the whole graph",                               "Home",   "graph"),
    ("stop_preview",  "Stop the pin preview",                                "Escape", "graph"),
    ("focus_mode",    "Focus mode: dim all but the selection",               "/",      "graph"),
    ("select_all",    "Select every node",                                   "A",      "graph"),
    ("select_none",   "Select nothing",                                      "Alt+A",  "graph"),
    ("select_invert", "Invert the selection",                                "Ctrl+Shift+I", "graph"),
    ("select_up",     "Select what feeds the selection too",                 "Ctrl+[", "graph"),
    ("select_down",   "Select what the selection feeds too",                 "Ctrl+]", "graph"),
    ("select_linked", "Select everything wired to the selection",            "Shift+L", "graph"),
    ("frame_selected", "Frame the selection",                                "Shift+Home", "graph"),
    ("snap",          "Snap to grid on / off (Ctrl while dragging: the other way)", "Shift+Tab", "graph"),
    ("dissolve",      "Delete and reconnect (what fed it feeds what it fed)", "Ctrl+Delete", "graph"),
    ("disconnect",    "Disconnect the selected nodes (every wire in and out)", "",       "graph"),
    ("swap_inputs",   "Swap a node's first two inputs",                      "Alt+S",  "graph"),
    ("label_node",    "Label the selected node",                             "Shift+F2", "graph"),
    ("frame_sel",     "Put a Frame round the selection",                     "Ctrl+J", "graph"),
    ("repeat",        "Repeat the last action",                              "Shift+R", "global"),
    ("palette",       "Command palette: every action by name",               "Ctrl+P", "global"),
    ("undo_history",  "Undo history",                                        "Ctrl+Alt+Z", "global"),
    ("history",       "History of the current graph or code",                "Ctrl+Shift+Y", "global"),
]

# Not rebindable; shown under the table.
FIXED = [("arrows / Shift+arrows", "nudge the selected nodes 10 / 1"),
         ("wheel / middle-drag", "zoom about the pointer / pan the graph"),
         ("right-click the graph", "add a node; on a node or pin, its menu"),
         ("drag a wire to empty space", "add a node wired to it"),
         ("Alt+click a node", "detach it from its wires"),
         ("Ctrl+Shift+click a node", "preview its output; again, the next output"),
         ("drag a node, pointer on a wire", "the wiring it would splice into shows; let go to do it"),
         ("drop a wire on a node", "its first free pin that fits"),
         ("Ctrl+right-drag", "a knife: cuts the wires it crosses"),
         ("Alt while editing a value", "the same on every selected node of that type"),
         ("Backspace over a value", "back to its default; Ctrl+wheel over a dropdown steps it"),
         ("double-click a sub-graph", "enter it"),
         ("click a pin", "preview that pin's value on the cube"),
         ("drag the bars between panes", "resize them")]

# key name <-> Dear PyGui codes. A name may have two codes (the number row
# and the keypad); the first is the one shown.
_NAMES = {
    "Space": ["Spacebar"], "Delete": ["Delete"], "Home": ["Home"], "End": ["End"], "Tab": ["Tab"],
    "Escape": ["Escape"], "Enter": ["Return", "NumPadEnter"], "Backspace": ["Back"], "Insert": ["Insert"],
    "Up": ["Up"], "Down": ["Down"], "Left": ["Left"], "Right": ["Right"], "PageUp": ["Prior"], "PageDown": ["Next"],
    "=": ["Plus", "Add", "NumPadEqual"], "-": ["Minus", "Subtract"], ".": ["Period", "Decimal"], ",": ["Comma"],
    "[": ["Open_Brace"], "]": ["Close_Brace"], "/": ["Slash", "Divide"], "\\": ["Backslash"], "`": ["Tilde"],
    ";": ["Colon"], "'": ["Quote"], "*": ["Multiply"],
}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _NAMES[_c] = [_c]
for _d in "0123456789":
    _NAMES[_d] = [_d, "NumPad" + _d]
for _f in range(1, 13):
    _NAMES[f"F{_f}"] = [f"F{_f}"]

NAME_TO_CODES = {}
CODE_TO_NAME = {}
for _n, _ks in _NAMES.items():
    codes = [getattr(dpg, "mvKey_" + k) for k in _ks if hasattr(dpg, "mvKey_" + k)]
    if codes:
        NAME_TO_CODES[_n] = codes
        for c in codes:
            CODE_TO_NAME.setdefault(c, _n)

MODIFIER_CODES = {getattr(dpg, "mvKey_" + k) for k in ("LControl", "RControl", "LShift", "RShift", "LAlt", "RAlt")
                  if hasattr(dpg, "mvKey_" + k)}


def combo(code):
    """The binding string for a key press now, with the modifiers held; None
    for a modifier on its own or a key with no name."""
    if code in MODIFIER_CODES:
        return None
    name = CODE_TO_NAME.get(code)
    if not name:
        return None
    mods = []
    if dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl):
        mods.append("Ctrl")
    if dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt):
        mods.append("Alt")
    if dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift):
        mods.append("Shift")
    return "+".join(mods + [name])


def valid(binding):
    parts = binding.split("+") if binding else []
    return bool(parts) and parts[-1] in NAME_TO_CODES and all(p in ("Ctrl", "Alt", "Shift") for p in parts[:-1])


class Keymap:
    def __init__(self, prefs):
        self.prefs = prefs
        self.defaults = {a: d for a, _, d, _ in ACTIONS}
        self.context = {a: c for a, _, _, c in ACTIONS}
        self.bind = dict(self.defaults)
        for a, b in (prefs.get("keys") or {}).items():
            if a in self.bind and (b == "" or valid(b)):
                self.bind[a] = b

    def label(self, action):
        return self.bind.get(action, "")

    def lookup(self, binding, ctx):
        """The action bound to `binding` that applies in context `ctx`; a
        graph binding wins over a global one while the graph is up."""
        found = None
        for a, b in self.bind.items():
            if b != binding:
                continue
            c = self.context[a]
            if c == ctx:
                return a
            if c == "global":
                found = a
        return found

    def set(self, action, binding):
        """Bind; whatever else had this key in a context that would clash
        loses it (a global key clashes with everything)."""
        if binding:
            for a, b in list(self.bind.items()):
                if a != action and b == binding and ("global" in (self.context[a], self.context[action])
                                                      or self.context[a] == self.context[action]):
                    self.bind[a] = ""
        self.bind[action] = binding
        self._save()

    def reset(self):
        self.bind = dict(self.defaults)
        self._save()

    def _save(self):
        changed = {a: b for a, b in self.bind.items() if b != self.defaults[a]}
        if changed:
            self.prefs["keys"] = changed
        else:
            self.prefs.pop("keys", None)
        from native.project import save_prefs
        save_prefs(self.prefs)
