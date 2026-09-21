"""A code editor drawn on a drawlist.

Dear PyGui's text box cannot colour its text, move its own cursor or say
where it is scrolled, so click-to-line and syntax colour were impossible
with it. This is an editor of our own: the text is lines drawn on a
drawlist in a monospace font, with a gutter, a cursor, a selection, and
C++ colouring; the keys come through the app's key handler and the typed
characters through a one-line text box kept focused behind the view (the
one way Dear PyGui hands over translated characters, and it brings paste
with it). The text itself lives in the hidden "code" value everything
else already reads and writes; the editor follows that value and writes
back to it, so find, replace, undo, metadata and the build are unchanged.

    ed = CodeEditor(app, parent)   # a child window in the code pane
    ed.resize(w, h)                # from relayout
    ed.poll()                      # every frame: mouse, the store, redraws
    ed.key(code, ctrl, shift)      # from the key handler: True if taken
    ed.goto(line)                  # scrolls there, marks the line
"""
import re
import time
import dearpygui.dearpygui as dpg

from native.graph_ui import _font_file

FONT_PX = 13
LINE_H = 17
GUTTER = 46
PAD = 6

KEYWORDS = set("""alignas alignof and asm auto bool break case catch char char16_t char32_t class const constexpr
const_cast continue decltype default delete do double dynamic_cast else enum explicit export extern false float
for friend goto if inline int long mutable namespace new noexcept not nullptr operator or private protected
public register reinterpret_cast return short signed sizeof static static_assert static_cast struct switch
template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile
wchar_t while uint8_t uint16_t uint32_t int8_t int16_t int32_t size_t uint64_t int64_t""".split())

COL_TEXT = (222, 226, 234, 255)
COL_DIM = (120, 128, 142, 255)
COL_COMMENT = (110, 122, 138, 255)
COL_STRING = (214, 170, 98, 255)
COL_NUMBER = (176, 212, 148, 255)
COL_KEYWORD = (150, 172, 255, 255)
COL_PREPROC = (204, 128, 204, 255)
COL_MACRO = (120, 200, 200, 255)
COL_SEL = (90, 169, 230, 70)
COL_LINE = (255, 255, 255, 12)
COL_ERR = (235, 80, 70, 70)
COL_CURSOR = (240, 244, 250, 255)
COL_GUTTER = (0, 0, 0, 40)
COL_FIND = (255, 184, 70, 80)
COL_FIND_CUR = (255, 184, 70, 160)
COL_BRACKET = (90, 169, 230, 110)
BRACKETS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {v: k for k, v in BRACKETS.items()}

TOKEN = re.compile(r'(//.*$)|(/\*.*?\*/)|(/\*.*$)|("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|'
                   r'(\b(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?)[fFuUlL]*\b)|([A-Za-z_]\w*)|(\s+)|(.)')


class CodeEditor:
    def __init__(self, app, parent):
        self.app = app
        self.lines = [""]
        self.cur = [0, 0]              # line, column
        self.anchor = None             # the other end of the selection, or None
        self.top = 0                   # first line shown
        self.left = 0                  # first column shown
        self.w = self.h = 0
        self.char_w = 7.0
        self.focus = False
        self.err_lines = set()
        self.mark = None               # a line to show (goto), until the next edit
        self.needle = ""               # the find text; its matches are highlighted
        self.find_at = None            # the match the cursor was last taken to
        self.find_case = False         # match case
        self.find_word = False         # whole words only
        self._needle_re = None
        self._store = None
        self._dirty = True
        self._items = []
        self._cursor_item = None
        self._blink = 0.0
        self._blink_on = True
        self._drag = False
        self._wrapped = []             # per line: starts inside a block comment
        self.font = None
        ff = _font_file()
        if ff:
            try:
                with dpg.font_registry():
                    self.font = dpg.add_font(ff, FONT_PX)
            except Exception:
                self.font = None
        with dpg.child_window(tag="code_ed_win", parent=parent, width=400, height=300, border=True,
                              no_scrollbar=True, no_scroll_with_mouse=True):
            # the character catcher: a one-line box behind the drawing, kept
            # focused while the editor has the keyboard
            dpg.add_input_text(tag="code_key", width=8, height=8, callback=self._on_chars, tab_input=True, pos=(1, 1))
            self.dl = dpg.add_drawlist(width=400, height=300, tag="code_ed", pos=(0, 0))
            if self.font:
                dpg.bind_item_font(self.dl, self.font)

    # --- geometry ---------------------------------------------------------------
    def resize(self, w, h):
        w, h = max(80, int(w)), max(40, int(h))
        if (w, h) != (self.w, self.h):
            self.w, self.h = w, h
            dpg.configure_item("code_ed_win", width=w, height=h)
            dpg.configure_item(self.dl, width=w - 2, height=h - 2)
            self._dirty = True

    @property
    def rows(self):
        return max(1, (self.h - 4) // LINE_H)

    @property
    def cols(self):
        return max(8, int((self.w - GUTTER - PAD - 8) / self.char_w))

    # --- the text: from and to the store ------------------------------------------
    def _sync_from_store(self):
        text = dpg.get_value("code")
        if text == self._store:
            return
        self._store = text
        self.lines = text.split("\n") if text is not None else [""]
        self._reflow()
        self.cur[0] = min(self.cur[0], len(self.lines) - 1)
        self.cur[1] = min(self.cur[1], len(self.lines[self.cur[0]]))
        self.anchor = None
        self._dirty = True

    def _commit(self):
        text = "\n".join(self.lines)
        self._store = text
        dpg.set_value("code", text)
        self.app.on_code_edit(None, text)
        self.mark = None
        self.err_lines = set()
        self._reflow()
        self._dirty = True

    def _reflow(self):
        """Which lines begin inside a block comment, so colouring is right
        for a comment that spans lines."""
        inside = False
        flags = []
        for ln in self.lines:
            flags.append(inside)
            i = 0
            while i < len(ln):
                if inside:
                    j = ln.find("*/", i)
                    if j < 0:
                        break
                    inside = False; i = j + 2
                else:
                    a, b = ln.find("/*", i), ln.find("//", i)
                    if a >= 0 and (b < 0 or a < b):
                        inside = True; i = a + 2
                    else:
                        break
        self._wrapped = flags

    # --- input --------------------------------------------------------------------
    def _on_chars(self, sender, value):
        if not value:
            return
        dpg.set_value("code_key", "")
        value = value.replace("\r", "")
        self._sync_from_store()
        self._insert(value)

    def _sel(self):
        """(start, end) of the selection as (line, col) pairs, ordered."""
        if self.anchor is None or tuple(self.anchor) == tuple(self.cur):
            return None
        a, b = tuple(self.anchor), tuple(self.cur)
        return (a, b) if a < b else (b, a)

    def _delete_sel(self):
        s = self._sel()
        if not s:
            return False
        (l0, c0), (l1, c1) = s
        self.lines[l0:l1 + 1] = [self.lines[l0][:c0] + self.lines[l1][c1:]]
        self.cur = [l0, c0]
        self.anchor = None
        return True

    def insert(self, text, indent=True):
        """Text put at the cursor from outside (the API reference): its
        later lines take the indent of the line it lands on."""
        self._sync_from_store()
        if indent and "\n" in text:
            l = self.cur[0]
            lead = self.lines[l][:len(self.lines[l]) - len(self.lines[l].lstrip(" "))]
            text = text.replace("\n", "\n" + lead)
        self._insert(text)
        self._dirty = True
        self.focus = True

    def _insert(self, text):
        self._delete_sel()
        l, c = self.cur
        if text == "}" and self.lines[l][:c].strip() == "" and self.lines[l][:c].startswith("  "):
            self.lines[l] = self.lines[l][2:]
            c = max(0, c - 2); self.cur = [l, c]
        parts = text.split("\n")
        head, tail = self.lines[l][:c], self.lines[l][c:]
        if len(parts) == 1:
            self.lines[l] = head + parts[0] + tail
            self.cur = [l, c + len(parts[0])]
        else:
            new = [head + parts[0]] + parts[1:-1] + [parts[-1] + tail]
            self.lines[l:l + 1] = new
            self.cur = [l + len(parts) - 1, len(parts[-1])]
        self._commit()
        self._show_cursor()

    def _move(self, l, c, shift):
        if shift:
            if self.anchor is None:
                self.anchor = list(self.cur)
        else:
            self.anchor = None
        l = max(0, min(len(self.lines) - 1, l))
        c = max(0, min(len(self.lines[l]), c))
        self.cur = [l, c]
        self._show_cursor()
        self._dirty = True

    def _show_cursor(self):
        l, c = self.cur
        if l < self.top:
            self.top = l
        elif l >= self.top + self.rows:
            self.top = l - self.rows + 1
        if c < self.left:
            self.left = c
        elif c >= self.left + self.cols:
            self.left = c - self.cols + 1
        self._blink, self._blink_on = time.time(), True

    def key(self, code, ctrl, shift):
        """A key while the editor has the keyboard. True when taken."""
        self._sync_from_store()
        l, c = self.cur
        K = dpg
        if code == K.mvKey_Left:
            if c > 0: self._move(l, c - 1, shift)
            elif l > 0: self._move(l - 1, len(self.lines[l - 1]), shift)
            return True
        if code == K.mvKey_Right:
            if c < len(self.lines[l]): self._move(l, c + 1, shift)
            elif l < len(self.lines) - 1: self._move(l + 1, 0, shift)
            return True
        if code == K.mvKey_Up:
            self._move(l - 1, c, shift); return True
        if code == K.mvKey_Down:
            self._move(l + 1, c, shift); return True
        if code == K.mvKey_Home:
            self._move(0 if ctrl else l, 0, shift); return True
        if code == K.mvKey_End:
            self._move(len(self.lines) - 1 if ctrl else l, len(self.lines[len(self.lines) - 1 if ctrl else l]), shift); return True
        if code == K.mvKey_Prior:
            self._move(l - self.rows, c, shift); self.top = max(0, self.top - self.rows); return True
        if code == K.mvKey_Next:
            self._move(l + self.rows, c, shift); self.top = min(max(0, len(self.lines) - 1), self.top + self.rows); return True
        if code == K.mvKey_Back:
            if self._delete_sel():
                self._commit()
            elif c > 0:
                self.lines[l] = self.lines[l][:c - 1] + self.lines[l][c:]; self.cur = [l, c - 1]; self._commit()
            elif l > 0:
                self.cur = [l - 1, len(self.lines[l - 1])]
                self.lines[l - 1:l + 1] = [self.lines[l - 1] + self.lines[l]]; self._commit()
            self._show_cursor(); return True
        if code == K.mvKey_Delete:
            if self._delete_sel():
                self._commit()
            elif c < len(self.lines[l]):
                self.lines[l] = self.lines[l][:c] + self.lines[l][c + 1:]; self._commit()
            elif l < len(self.lines) - 1:
                self.lines[l:l + 2] = [self.lines[l] + self.lines[l + 1]]; self._commit()
            return True
        if code in (K.mvKey_Return, K.mvKey_NumPadEnter):
            # keep the line's indent; one more step after an opening brace,
            # and a closing brace typed next lands back out
            line = self.lines[l]
            indent = re.match(r"[ \t]*", line).group(0)
            before = line[:c].rstrip()
            after = line[c:].lstrip()
            if before.endswith("{"):
                if after.startswith("}"):
                    self._insert("\n" + indent + "  " + "\n" + indent)
                    self._move(self.cur[0] - 1, len(indent) + 2, False)
                else:
                    self._insert("\n" + indent + "  ")
            else:
                self._insert("\n" + indent)
            return True
        if code == K.mvKey_Tab:
            s_ = self._sel()
            if s_ and s_[0][0] != s_[1][0]:
                (l0, c0), (l1, c1) = s_
                for i in range(l0, l1 + 1):
                    ln_ = self.lines[i]
                    if shift:
                        lead = len(ln_) - len(ln_.lstrip(" "))
                        self.lines[i] = ln_[min(2, lead):]
                    else:
                        self.lines[i] = "  " + ln_
                self.anchor = [l0, 0]; self.cur = [l1, len(self.lines[l1])]
                self._commit(); return True
            if shift:
                if self.lines[l].startswith("  "):
                    self.lines[l] = self.lines[l][2:]; self.cur = [l, max(0, c - 2)]; self._commit()
                return True
            return False                                   # the catcher inserts the tab characters
        if code == K.mvKey_Escape:
            self.anchor = None; self._dirty = True; return True
        if ctrl and code == K.mvKey_A:
            self.anchor = [0, 0]; self.cur = [len(self.lines) - 1, len(self.lines[-1])]; self._dirty = True; return True
        if ctrl and code in (K.mvKey_C, K.mvKey_X):
            s = self._sel()
            if s:
                (l0, c0), (l1, c1) = s
                if l0 == l1:
                    text = self.lines[l0][c0:c1]
                else:
                    text = "\n".join([self.lines[l0][c0:]] + self.lines[l0 + 1:l1] + [self.lines[l1][:c1]])
                dpg.set_clipboard_text(text)
                if code == K.mvKey_X:
                    self._delete_sel(); self._commit()
            return True
        if ctrl and code == K.mvKey_D:                 # duplicate the line
            self.lines.insert(l + 1, self.lines[l]); self.cur = [l + 1, c]; self._commit(); return True
        if ctrl and code == K.mvKey_Slash:              # toggle a line comment
            s = self._sel()
            l0, l1 = (s[0][0], s[1][0]) if s else (l, l)
            allc = all(self.lines[i].lstrip().startswith("//") for i in range(l0, l1 + 1) if self.lines[i].strip())
            for i in range(l0, l1 + 1):
                ln = self.lines[i]
                if not ln.strip():
                    continue
                k = len(ln) - len(ln.lstrip())
                self.lines[i] = (ln[:k] + ln[k:].replace("//", "", 1).lstrip(" ")) if allc else (ln[:k] + "// " + ln[k:])
            self._commit(); return True
        return False

    # --- find --------------------------------------------------------------------------
    def set_needle(self, text, case=None, word=None):
        """The find text, and how it matches: case as typed, whole words."""
        was = (self.needle, self.find_case, self.find_word)
        if case is not None:
            self.find_case = bool(case)
        if word is not None:
            self.find_word = bool(word)
        self.needle = (text or "")
        if (self.needle, self.find_case, self.find_word) != was:
            self.find_at = None                            # a new search starts from the cursor; the same one goes on
        pat = re.escape(self.needle)
        if self.find_word:
            pat = r"(?<!\w)" + pat + r"(?!\w)"
        self._needle_re = re.compile(pat, 0 if self.find_case else re.IGNORECASE) if self.needle else None
        self._dirty = True

    def _line_matches(self, li):
        """The columns the needle occurs at on line li."""
        if self._needle_re is None:
            return []
        return [m.start() for m in self._needle_re.finditer(self.lines[li])]

    def matches(self):
        """Every (line, col) the needle occurs at, as the options say."""
        if self._needle_re is None:
            return []
        return [(li, c) for li in range(len(self.lines)) for c in self._line_matches(li)]

    def find_place(self):
        """(k, n): the match the cursor is on (1-based, 0 when on none) and how many there are."""
        ms = self.matches()
        if not ms or self.find_at is None:
            return 0, len(ms)
        cur = (self.find_at[0], self.find_at[1] - len(self.needle))
        return (ms.index(cur) + 1 if cur in ms else 0), len(ms)

    def replace_current(self, repl):
        """The match the cursor is on becomes `repl` and the next is found;
        on none, the next is found first. True when something was replaced."""
        self._sync_from_store()
        ms = self.matches()
        if not ms:
            return False
        cur = None if self.find_at is None else (self.find_at[0], self.find_at[1] - len(self.needle))
        if cur not in ms:
            self.find_next(); return False
        li, c = cur
        n = len(self.needle)
        self.lines[li] = self.lines[li][:c] + repl + self.lines[li][c + n:]
        self.cur = [li, c + len(repl)]
        self.anchor = None
        self.find_at = None
        self._commit()
        self.find_next()
        return True

    def find_next(self, backwards=False):
        """The cursor to the next match after it (or before, backwards),
        wrapping round; the match is selected."""
        self._sync_from_store()
        ms = self.matches()
        if not ms:
            return False
        cur = tuple(self.cur)
        if backwards:
            cands = [m for m in ms if m < (cur[0], cur[1] - (len(self.needle) if self.find_at == cur else 0))]
            m = cands[-1] if cands else ms[-1]
        else:
            cands = [m for m in ms if m > cur or (m == cur and self.find_at != cur)]
            m = cands[0] if cands else ms[0]
        self.anchor = [m[0], m[1]]
        self.cur = [m[0], m[1] + len(self.needle)]
        self.find_at = (m[0], m[1] + len(self.needle))
        self.top = max(0, min(max(0, len(self.lines) - self.rows), m[0] - self.rows // 3)) if not (self.top <= m[0] < self.top + self.rows) else self.top
        self._show_cursor()
        self._dirty = True
        return True

    # --- brackets ----------------------------------------------------------------------
    def _bracket_pair(self):
        """(here, there) for a bracket at or before the cursor, or None."""
        l, c = self.cur
        ln = self.lines[l]
        for pos in (c, c - 1):
            if 0 <= pos < len(ln) and (ln[pos] in BRACKETS or ln[pos] in CLOSERS):
                ch = ln[pos]
                fwd = ch in BRACKETS
                other = BRACKETS.get(ch) or CLOSERS.get(ch)
                depth = 0
                li, ci = l, pos
                step = 1 if fwd else -1
                while 0 <= li < len(self.lines):
                    row = self.lines[li]
                    while 0 <= ci < len(row):
                        x = row[ci]
                        if x == ch:
                            depth += 1
                        elif x == other:
                            depth -= 1
                            if depth == 0:
                                return (l, pos), (li, ci)
                        ci += step
                    li += step
                    ci = 0 if fwd else (len(self.lines[li]) - 1 if 0 <= li < len(self.lines) else 0)
                    if abs(li - l) > 400:
                        break
                return None
        return None

    def wheel(self, d):
        self.top = max(0, min(max(0, len(self.lines) - self.rows), self.top - int(d) * 3))
        self._dirty = True

    def goto(self, line, col=0):
        """Scroll to a line (1-based) and mark it."""
        self._sync_from_store()
        l = max(0, min(len(self.lines) - 1, int(line) - 1))
        self.cur = [l, min(col, len(self.lines[l]))]
        self.anchor = None
        self.top = max(0, l - self.rows // 3)
        self.mark = l
        self._dirty = True
        self._blink, self._blink_on = time.time(), True

    # --- each frame ------------------------------------------------------------------
    def _mouse_to_pos(self):
        mx, my = dpg.get_mouse_pos(local=False)
        x0, y0 = dpg.get_item_rect_min(self.dl)
        row = int((my - y0 - 2) // LINE_H)
        col = int(round((mx - x0 - GUTTER - PAD) / self.char_w))
        l = max(0, min(len(self.lines) - 1, self.top + row))
        c = max(0, min(len(self.lines[l]), self.left + col))
        return l, c

    def poll(self):
        if not dpg.does_item_exist(self.dl) or not dpg.is_item_shown("code_ed_win"):
            return
        self._sync_from_store()
        if self.char_w == 7.0 and self.font:
            try:
                w = dpg.get_text_size("MMMMMMMMMM", font=self.font)
                if w and w[0] > 0:
                    self.char_w = w[0] / 10.0
                    self._dirty = True
            except Exception:
                pass
        hovered = dpg.is_item_hovered(self.dl)
        if dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            if hovered and not self._drag and dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left):
                l, c = self._mouse_to_pos()
                shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
                self._move(l, c, shift)
                self._drag = True
                dpg.focus_item("code_key")
                self.focus = True
            elif self._drag:
                l, c = self._mouse_to_pos()
                if [l, c] != self.cur:
                    self._move(l, c, True)
        else:
            self._drag = False
        if self.focus and not dpg.is_item_focused("code_key"):
            # the box lost the keyboard to something else - a click elsewhere
            if dpg.is_mouse_button_clicked(dpg.mvMouseButton_Left) and not hovered:
                self.focus = False
                self._dirty = True
            else:
                dpg.focus_item("code_key")
        if self.focus:
            now = time.time()
            on = ((now - self._blink) % 1.0) < 0.55
            if on != self._blink_on:
                self._blink_on = on
                self._draw_cursor()
        if self._dirty:
            self._render()

    # --- drawing -------------------------------------------------------------------------
    def _render(self):
        self._dirty = False
        for it in self._items:
            if dpg.does_item_exist(it):
                dpg.delete_item(it)
        self._items = []
        self._cursor_item = None
        W, H = self.w - 2, self.h - 2
        add = self._items.append
        add(dpg.draw_rectangle((0, 0), (GUTTER, H), parent=self.dl, color=(0, 0, 0, 0), fill=COL_GUTTER))
        sel = self._sel()
        x_text = GUTTER + PAD
        for r in range(self.rows):
            li = self.top + r
            if li >= len(self.lines):
                break
            y = 2 + r * LINE_H
            if li == self.cur[0] and self.focus:
                add(dpg.draw_rectangle((GUTTER, y), (W, y + LINE_H), parent=self.dl, color=(0, 0, 0, 0), fill=COL_LINE))
            if li in self.err_lines or li == self.mark:
                add(dpg.draw_rectangle((GUTTER, y), (W, y + LINE_H), parent=self.dl, color=(0, 0, 0, 0),
                                       fill=COL_ERR if li in self.err_lines else COL_SEL))
            if sel:
                (l0, c0), (l1, c1) = sel
                if l0 <= li <= l1:
                    a = c0 if li == l0 else 0
                    b = c1 if li == l1 else len(self.lines[li]) + 1
                    xa = x_text + (a - self.left) * self.char_w
                    xb = x_text + (b - self.left) * self.char_w
                    add(dpg.draw_rectangle((max(GUTTER, xa), y), (min(W, xb), y + LINE_H), parent=self.dl,
                                           color=(0, 0, 0, 0), fill=COL_SEL))
            if self.needle:
                n = len(self.needle)
                for i in self._line_matches(li):
                    xa = x_text + (i - self.left) * self.char_w
                    xb = xa + n * self.char_w
                    if xb > GUTTER and xa < W:
                        current = self.find_at == (li, i + n)
                        add(dpg.draw_rectangle((max(GUTTER, xa), y + 1), (min(W, xb), y + LINE_H - 1), parent=self.dl,
                                               color=(0, 0, 0, 0), fill=COL_FIND_CUR if current else COL_FIND, rounding=2))
            add(dpg.draw_text((4, y + 1), f"{li + 1:>5}", parent=self.dl, color=COL_DIM, size=FONT_PX))
            self._draw_line(li, x_text, y + 1, W)
        if self.focus:
            pair = self._bracket_pair()
            if pair:
                for (bl, bc) in pair:
                    r = bl - self.top
                    if 0 <= r < self.rows:
                        xa = x_text + (bc - self.left) * self.char_w
                        add(dpg.draw_rectangle((xa, 2 + r * LINE_H + 1), (xa + self.char_w, 2 + r * LINE_H + LINE_H - 1),
                                               parent=self.dl, color=COL_BRACKET, fill=COL_BRACKET, rounding=2))
        self._draw_cursor()

    def _draw_line(self, li, x0, y, W):
        ln = self.lines[li]
        shown = ln[self.left:self.left + self.cols + 1]
        if not shown:
            return
        inside = self._wrapped[li] if li < len(self._wrapped) else False
        x = x0
        pre = ln.lstrip().startswith("#")
        # colour the whole visible run token by token; the block-comment
        # state carries in from earlier lines
        pos = 0
        if inside:
            j = shown.find("*/")
            seg = shown if j < 0 else shown[:j + 2]
            self._items.append(dpg.draw_text((x, y), seg, parent=self.dl, color=COL_COMMENT, size=FONT_PX))
            if j < 0:
                return
            x += len(seg) * self.char_w
            pos = j + 2
        for m in TOKEN.finditer(shown, pos):
            t = m.group(0)
            if m.group(7):                              # whitespace
                x += len(t) * self.char_w
                continue
            if m.group(1) or m.group(2) or m.group(3):
                col = COL_COMMENT
            elif m.group(4):
                col = COL_STRING
            elif m.group(5):
                col = COL_NUMBER
            elif m.group(6):
                col = COL_PREPROC if pre else (COL_KEYWORD if t in KEYWORDS else (COL_MACRO if t.isupper() and len(t) > 2 else COL_TEXT))
            else:
                col = COL_TEXT
            if x < W:
                self._items.append(dpg.draw_text((x, y), t, parent=self.dl, color=col, size=FONT_PX))
            x += len(t) * self.char_w
            if m.group(3):
                break

    def _draw_cursor(self):
        if self._cursor_item and dpg.does_item_exist(self._cursor_item):
            dpg.delete_item(self._cursor_item)
        self._cursor_item = None
        if not self.focus or not self._blink_on:
            return
        l, c = self.cur
        r = l - self.top
        if r < 0 or r >= self.rows:
            return
        x = GUTTER + PAD + (c - self.left) * self.char_w
        y = 2 + r * LINE_H
        self._cursor_item = dpg.draw_line((x, y + 1), (x, y + LINE_H - 1), parent=self.dl, color=COL_CURSOR, thickness=1.5)
