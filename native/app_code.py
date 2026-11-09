"""The code pane's tools - a mixin of app.py's App: the external editor and the file watcher, find and replace, the metadata string as a form, and undo for the code box."""
import os
import re
import time
import dearpygui.dearpygui as dpg
from native.typeface import px
from native import form
from native import chrome, procs
import shutil


class AppCode:
    # --- the external editor and the file watcher -------------------------------------
    # The in-app box is for quick fixes. For real editing the file opens in
    # whatever editor the system has - VS Code if it is on the path, else the
    # .cpp association - and the watcher reloads the pane (and rebuilds, when
    # "watch" is ticked) each time the file is saved there. Click-to-line
    # goes to the same editor, since the in-app box cannot move its cursor.
    def _mtime(self, fname):
        try:
            return os.path.getmtime(self.project.effect_path(fname))
        except OSError:
            return None

    def editor_command(self):
        """The command that opens a file at a line, as a list with {file} and
        {line} holes; from the studio's own settings (never the project's: a
        project from elsewhere chose the program Edit ran), else VS Code, else
        none."""
        cmd = (getattr(self, "prefs", None) or {}).get("editor")
        if cmd:
            if isinstance(cmd, list):
                return cmd
            import shlex
            try:                                         # a quoted program's path kept whole (C:\Program Files\...)
                if os.name != "nt":
                    return shlex.split(cmd)                  # POSIX: its own quotes ('{file}:{line}') taken out
                return [c.replace('"', "") for c in shlex.split(cmd, posix=False)]   # (--file="{file}" too)
            except ValueError:
                return cmd.split()
        code = shutil.which("code") or shutil.which("code.cmd")
        if code:
            return [code, "-g", "{file}:{line}"]
        return None

    def open_external(self, line=1):
        if not self.edit_file:
            return
        if self.edit_dirty:
            self.edit_save()
        path = self.project.effect_path(self.edit_file)
        cmd = self.editor_command()
        try:
            if cmd:
                procs.popen([c.replace("{file}", path).replace("{line}", str(line)) for c in cmd])
                dpg.set_value("edit_status", f"opened in {os.path.basename(cmd[0])} - saves there reload here")
            elif hasattr(os, "startfile"):
                os.startfile(path)
                dpg.set_value("edit_status", "opened in the system's .cpp editor - saves there reload here")
            else:
                opener = shutil.which("xdg-open") or shutil.which("open")
                if opener:
                    procs.popen([opener, path])
                dpg.set_value("edit_status", "opened externally - saves there reload here")
        except Exception as e:
            dpg.set_value("edit_status", f"could not open an editor: {e}")
        if dpg.does_item_exist("edit_watch"):
            dpg.set_value("edit_watch", True)

    def poll_watch(self):
        """Twice a second: has the file been saved outside? Then the pane
        takes the new text, unless it has unsaved edits of its own, and a
        watched file rebuilds."""
        now = time.time()
        if now - self._watch_at < 0.5 or not self.edit_file:
            return
        self._watch_at = now
        m = self._mtime(self.edit_file)
        if m is None or m == self._watch_mtime:
            return
        self._watch_mtime = m
        if self.edit_dirty:
            dpg.set_value("edit_status", f"{self.edit_file} changed on disk - unsaved edits here, not reloaded")
            return
        dpg.set_value("code", self.project.read_effect(self.edit_file))
        dpg.set_value("edit_status", f"{self.edit_file} reloaded from disk")
        if dpg.does_item_exist("edit_watch") and dpg.get_value("edit_watch") and not self.building:
            self.edit_build()

    def goto_code(self, fname, line):
        """A message's line of code: the file open in the code pane, at the line."""
        if fname and fname not in self.project.effect_files():
            self.gp.status(f"{fname} is not one of this project's effects"); return
        if fname and fname != self.edit_file:
            self.edit_open(fname)
        self.show_pane("edit")
        self.goto_line(line)

    def goto_line(self, line):
        """An error or find row was clicked: the editor goes to that line;
        the external editor too when the file is being watched there."""
        text = dpg.get_value("code").split("\n")
        if 1 <= line <= len(text):
            dpg.set_value("edit_status", f"line {line}: {text[line - 1].strip()[:90]}")
        if self.code_ed is not None:
            self.code_ed.goto(line)
            self.code_ed.focus = True
            dpg.focus_item("code_key")
        if dpg.get_value("edit_watch"):
            self.open_external(line)

    # --- find and replace ----------------------------------------------------------------
    def _find_setup(self):
        """The find text and its options into the editor; the needle."""
        needle = dpg.get_value("find_text")
        if self.code_ed is not None:
            self.code_ed.set_needle(needle, case=dpg.get_value("find_case") if dpg.does_item_exist("find_case") else None,
                                    word=dpg.get_value("find_word") if dpg.does_item_exist("find_word") else None)
        return needle

    def find(self, backwards=None):
        """Find: the next match (Shift+Enter, the previous), the place and
        count in the status, and every matching line as rows that go to
        the line."""
        needle = self._find_setup()
        dpg.delete_item("edit_errors", children_only=True)
        if backwards is None:
            backwards = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
        if self.code_ed is not None and needle:
            self.code_ed.find_next(backwards)
            self.code_ed.focus = True
            dpg.focus_item("code_key")
        if not needle:
            dpg.set_value("edit_status", ""); return
        self.find_status()
        if self.code_ed is not None:
            hits = sorted({li for li, _ in self.code_ed.matches()})
            lines = self.code_ed.lines
        else:
            lines = dpg.get_value("code").split("\n")
            hits = [i for i, l in enumerate(lines) if needle.lower() in l.lower()]
        for li in hits[:40]:
            self._error_row(f"{li + 1}: {lines[li].strip()}", li + 1, lambda s, a, u: self.goto_line(u))

    def _error_row(self, text, user_data, callback):
        """A row under the code (a compiler message, a find hit): as wide as the pane lets it be, ending in "..."
        when longer, the whole of it on hover - at 140 characters a message ran past the pane, which scrolled."""
        avail = (dpg.get_item_rect_size("edit_win")[0] or px(420)) - px(40)
        shown = chrome._fit_text(text, avail)
        row = dpg.add_selectable(label=shown, parent="edit_errors", user_data=user_data, callback=callback)
        if shown != text:
            chrome.tip(text, item=row)
        return row

    def find_status(self):
        if self.code_ed is None:
            return
        k, n = self.code_ed.find_place()
        dpg.set_value("edit_status", (f"{k} of {n}" if k else f"{n} match(es)") if n else "no match")

    def replace_one(self):
        """The match the cursor is on becomes the replacement, and the next is found."""
        needle = self._find_setup(); repl = dpg.get_value("replace_text")
        if not needle or self.code_ed is None:
            return
        done = self.code_ed.replace_current(repl)
        self.edit_dirty = self.edit_dirty or done
        self.find_status()
        if done:
            dpg.set_value("edit_status", "replaced one - " + dpg.get_value("edit_status"))

    def replace_all(self):
        needle = self._find_setup(); repl = dpg.get_value("replace_text")
        if not needle:
            return
        if self.code_ed is not None:
            self.code_ed._sync_from_store()
            rx = self.code_ed._needle_re
            text = "\n".join(self.code_ed.lines)
            new, n = rx.subn(lambda m: repl, text)
        else:
            text = dpg.get_value("code")
            n = text.count(needle); new = text.replace(needle, repl)
        if n:
            dpg.set_value("code", new)
            self.edit_dirty = True
        dpg.set_value("edit_status", f"replaced {n} occurrence(s)")
        self.find()

    # --- the metadata string, as a form ----------------------------------------------
    # Name@slider labels;colour labels;palette;flags;defaults - a line most
    # people get wrong once. The form reads it out of the pane and writes it
    # back, so the fields are edited by name.
    META_FIELDS = ("meta_name", "meta_labels", "meta_colours", "meta_flags", "meta_defaults")

    def meta_read(self):
        m = re.search(r'PROGMEM\s*=\s*"([^"]*)"', dpg.get_value("code"))
        if not m:
            dpg.set_value("edit_status", "no metadata string in this file"); return
        text = m.group(1)
        name, _, rest = text.partition("@")
        parts = (rest.split(";") + ["", "", "", "", ""])[:5]
        for tag, v in zip(self.META_FIELDS, [name, parts[0], parts[1], parts[3], parts[4]]):
            dpg.set_value(tag, v)
        dpg.set_value("edit_status", "metadata read from the file")

    def meta_write(self):
        code = dpg.get_value("code")
        m = re.search(r'(PROGMEM\s*=\s*")([^"]*)(")', code)
        if not m:
            dpg.set_value("edit_status", "no metadata string in this file"); return
        name, labels, colours, flags, defaults = (dpg.get_value(t).replace('"', "'").replace(";", " ") if t == "meta_name"
                                                  else dpg.get_value(t).replace('"', "'") for t in self.META_FIELDS)
        new = f"{name}@{labels};{colours};!;{flags};{defaults}"
        dpg.set_value("code", code[:m.start(2)] + new + code[m.end(2):])
        self.edit_dirty = True
        dpg.set_value("edit_status", f"metadata: {new[:100]}")

    def api_pick(self, snippet, label):
        """A click on the API reference puts the snippet at the cursor (the
        in-app editor takes an insertion); the clipboard gets it too, for
        an external editor."""
        dpg.set_clipboard_text(snippet)
        if self.code_ed is not None and dpg.does_item_exist("code_ed"):
            self.code_ed.insert(snippet)
            dpg.set_value("edit_status", f"inserted at the cursor: {label} (and copied)")
        else:
            dpg.set_value("edit_status", f"copied: {label} - Ctrl+V to paste at the cursor")

    def refresh_import_buttons(self):
        """The File menu says what it will do to the current file, and its
        open lists follow the project."""
        chrome.refresh_files(self)

    def toggle_import(self, fname):
        """A draft joins the effects list, or leaves it. Either way the engine
        is rebuilt so the roster shows the list as it now is."""
        if not fname or fname not in self.project.effect_files():
            return
        on = not self.project.is_imported(fname)
        self.project.set_imported(fname, on)
        self.refresh_import_buttons()
        title = self.project.effect_title(fname)
        msg = f"{title} added to the effects list" if on else f"{title} removed from the effects list"
        dpg.set_value("edit_status", msg); self.gp.status(msg)
        self.edit_build()

    def ensure_built(self):
        """The file just opened for editing is previewed: if the engine does
        not have it - a draft that was not the last one built - build now."""
        if self.edit_file and self.project.effect_title(self.edit_file) not in self.eng.names:
            self.edit_build()

    def edit_rename(self, title):
        """The current effect takes a new name."""
        title = (title or "").strip()
        if not title or not self.edit_file:
            dpg.set_value("edit_status", "a name is needed to rename")
            return
        if self.edit_dirty:
            self.edit_save()
        new = self.project.rename_effect(self.edit_file, title)
        self.edit_open(new)
        dpg.set_value("edit_status", f"renamed to {title} ({new})")
        self.edit_build()

    def edit_new(self, title=None):
        title = (title or "").strip() or "New Effect"
        fname = self.project.new_effect(title)
        self.edit_open(fname)

    def edit_save(self):
        if not self.edit_file:
            return
        self.project.write_effect(self.edit_file, dpg.get_value("code"))
        self._watch_mtime = self._mtime(self.edit_file)      # the pane's own save: not a change from outside for the watcher
        self.edit_dirty = False
        dpg.set_value("edit_status", f"{self.edit_file} saved")

    # --- undo for the code box -----------------------------------------------
    # The box reports its whole text on every keystroke. Edits within a
    # second of each other share one undo step, as the graph's do, so undo
    # steps back over a word or a line, not a character. (While the box has
    # the keyboard, Ctrl+Z is its own; these are for the menu, the toolbar
    # and the key once the box is left.)
    def on_code_edit(self, s, v):
        self.edit_dirty = True
        self._code_edits = getattr(self, "_code_edits", 0) + 1
        now = time.time()
        if now - self._code_t > 0.6:                     # a pause in typing ends an undo step
            self._code_undo.append(self._code_text)
            del self._code_undo[:-200]
            self._code_redo.clear()
        self._code_t = now
        self._code_text = v

    def _code_reset(self, text):
        self._code_undo, self._code_redo = [], []
        self._code_text, self._code_t = text, 0.0

    def code_undo(self):
        if not self._code_undo:
            dpg.set_value("edit_status", "nothing to undo"); return
        self._code_redo.append(dpg.get_value("code"))
        self._code_text = self._code_undo.pop()
        dpg.set_value("code", self._code_text)
        self.edit_dirty = True
        self._code_t = 0.0
        dpg.set_value("edit_status", f"undo ({len(self._code_undo)} more)")

    def code_redo(self):
        if not self._code_redo:
            dpg.set_value("edit_status", "nothing to redo"); return
        self._code_undo.append(dpg.get_value("code"))
        self._code_text = self._code_redo.pop()
        dpg.set_value("code", self._code_text)
        self.edit_dirty = True
        self._code_t = 0.0
        dpg.set_value("edit_status", f"redo ({len(self._code_redo)} more)")

    def open_graph_code(self):
        """Generate the graph's C++ and show it in the code pane - the hand-off
        for the cases the nodes cannot reach. From here it is a code effect."""
        fname = self.gp.compile(and_build=False)
        if fname:
            self.layout = "edit"; self.ui = True; self.request_layout()
            self.edit_open(fname)

    def on_color(self, i, rgb):
        """A segment colour from its swatch or its hex (0..255 each)."""
        r, g, b = rgb
        self.seg_cols[int(i)] = (r << 16) | (g << 8) | b
        self.eng.colors(*self.seg_cols)
        self._ab_sync()

    @staticmethod
    def rgb_of(c):
        return ((int(c) >> 16) & 255, (int(c) >> 8) & 255, int(c) & 255)

    def refresh_colours(self):
        """The COLOURS rows show the colours in force (a sequence step loaded them)."""
        for i, c in enumerate(self.seg_cols[:3]):
            form.set_colour(f"seg_col_{i}", self.rgb_of(c))

    def _set_param(self, k, v):
        self.eng.fx[k] = int(v)
        self.eng.push()

    def on_check(self, sender, val):
        self.eng.fx[dpg.get_item_user_data(sender)] = 1 if val else 0
        self.eng.push()
