"""The mouse and the keys - a mixin of app.py's App: grab and turn, clicks, drags, the wheel, the keys and the actions they run, undo's target and repeat."""
import time
import dearpygui.dearpygui as dpg
from native.typeface import px
from native import num
from native import typeface
from native import dock
from native import messages
from native.project import pref_num, save_prefs
from native import chrome, device_ui, shape_ui, midi_ui, bank_ui, reader_ui, room, weight, view3d, shape_tools
from native.keys import combo as key_combo
from native.app_layout import VIEW_MIN


class AppInput:
    # --- interaction ---------------------------------------------------------
    # --- grab and turn --------------------------------------------------------
    # The angle at the start of a drag is captured ONCE, on the press, and every
    # later position is that angle plus the total drag delta. That is what makes
    # it feel like holding the object: let go of the mouse without moving and
    # the cube does not drift.
    #
    # It used to capture on mvMouseDownHandler, which fires every frame the
    # button is held rather than once when it goes down. So the "starting" angle
    # was re-taken continuously and the drag delta was added to it again each
    # frame - the cube span at a rate proportional to how far the pointer had
    # moved from where the drag began. A spin control, not a grab, exactly as it
    # felt.
    def _picker_click(self):
        """A colour swatch or a dropdown clicked opens an ImGui popup, which
        nothing reports; it is remembered, and the frames stay off while it
        is - they would draw over it. A dropdown closes on the next click
        wherever it lands (a choice, or a dismissal); a picker stays open
        for clicks inside it, so only a click outside where it sits (under
        the swatch) forgets it. Escape forgets either."""
        if self._color_edits is None:
            self._color_edits = [i for i in dpg.get_all_items()
                                 if dpg.get_item_type(i).endswith(("::mvColorEdit", "::mvCombo"))]
        prev = self._picker
        self._popup_click = prev is not None                  # this click went to a popup: not a selection
        self._picker = None                                   # a dropdown, or a click elsewhere: over
        for i in list(self._color_edits):
            if not dpg.does_item_exist(i):
                self._color_edits = None                      # stale: found again next click
                return
            if dpg.is_item_shown(i) and dpg.is_item_hovered(i):
                if i == prev and dpg.get_item_type(i).endswith("::mvCombo"):
                    return                                    # clicked again: it closed
                self._picker = i
                return
        if prev is not None and dpg.does_item_exist(prev) and dpg.get_item_type(prev).endswith("::mvColorEdit"):
            st = dpg.get_item_state(prev)
            mx, my = dpg.get_mouse_pos(local=False)
            (x0, _), (_, y1) = st.get("rect_min", (0, 0)), st.get("rect_max", (0, 0))
            if x0 - 4 <= mx <= x0 + 360 and y1 <= my <= y1 + 380:
                self._picker = prev                           # inside the picker: still open

    def _slot_label(self, slot):
        return {"main": {"edit": "Code", "graph": "Graph"}.get(self.layout, "Logical view"), "cube": "3-D view",
                "side": "Panel", "props": "Properties", "devices": "Devices", "flash": "Flash firmware",
                "send": "Send to device", "shape": "Shape", "sequence": "Sequence", "library": "Library", "palettes": "Palettes", "outputs": "LED outputs", "audioin": "Audio input", "vj": "VJ"}.get(slot, slot)

    def on_mouse_click(self, sender, app_data):
        self._picker_click()
        reader_ui.clicked(self)
        if room.press(self):
            return                                       # the 3-D view's ::: or size handle, over the graph
        if dpg.does_item_exist("help_split") and dpg.is_item_shown("help_split") and dpg.is_item_hovered("help_split"):
            self._split_drag = ("help_split", dpg.get_mouse_pos(local=False)[1], int(pref_num(self.prefs, "help_h", 46)))
            return
        for slot in self._rects:
            grip = f"grip_{self.pane_of(slot)}"
            if dpg.does_item_exist(grip) and dpg.is_item_hovered(grip):
                self._pane_drag = slot
                self._pane_target = None
                x, y, w, h = self._rects[slot]
                self._ghost_start(x, y, w, h, self._slot_label(slot))
                return
        for slot in self.OPTIONAL:
            tag = self.pane_of(slot)
            grip = f"grip_{tag}"
            if not self.docked(slot) and dpg.does_item_exist(grip) and dpg.is_item_shown(tag) and dpg.is_item_hovered(grip):
                self._pane_drag = slot
                self._pane_target = None
                x, y = dpg.get_item_pos(tag)
                w, h = dpg.get_item_rect_size(tag)
                self._ghost_start(x, y, w, h, self._slot_label(slot))
                return
        if self.side and self.ui:
            for key in self.SECTIONS:
                grip = f"sec_{key}_grip"
                if dpg.does_item_exist(grip) and dpg.is_item_hovered(grip):
                    self._sec_drag = key
                    self._sec_target = None
                    st = dpg.get_item_state(f"sec_{key}")
                    if "rect_min" in st and "rect_size" in st:
                        (x, y), (w, h) = st["rect_min"], st["rect_size"]
                        self._ghost_start(x, y, w, h, dpg.get_value(f"sec_{key}_title") if dpg.does_item_exist(f"sec_{key}_title") else key.upper())
                    return
        mp = dpg.get_mouse_pos(local=False)
        for tag, (kind, i, j) in self._splitters.items():
            if not (dpg.is_item_shown(tag) and dpg.is_item_hovered(tag)):
                continue
            cols = self._cols
            if kind == "v":
                if cols[i] == ["side"] or cols[i + 1] == ["side"]:
                    # the dock keeps a pixel width - the panel's, or the frame's in front: the splitter moves that
                    self._split_drag = (tag, mp[0], ("side", 1 if cols[i] == ["side"] else -1, dock.width(self)))
                else:
                    fr = self._col_fracs(cols)
                    self._split_drag = (tag, mp[0], ("col", i, fr[i], fr[i + 1]))
            else:
                rf = self._row_fracs(cols[i])
                self._split_drag = (tag, mp[1], ("row", i, j, rf[j], rf[j + 1]))
            return
        if dpg.is_item_hovered("cube_img"):
            if shape_ui.click(self):                 # placing an LED, or picking one up
                return
            if shape_tools.press(self):              # a handle taken, a box begun, a modal move kept
                return
            if dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl):
                self._pan_drag = [0.0, 0.0]          # Ctrl+drag pans (a touchpad has no middle button)
            else:
                self._dragging = True
                self._yaw0, self._pitch0 = self.yaw, self.pitch
        mx, my = dpg.get_mouse_pos(local=False)
        for tag in ("net_win", "cube_win", "edit_win", "graph_win", "side_win", "props_win") + tuple(t for t, _, _, _ in device_ui.FRAMES.values()):
            if not (dpg.does_item_exist(tag) and dpg.is_item_shown(tag)):
                continue
            hit = dpg.is_item_hovered(tag)
            if not hit and tag in self.docked_tags():
                # a docked frame by where it is: "hovered" is false over its list or its timeline (a child window,
                # a drawlist), and a click there left the keyboard elsewhere - Undo, Space, Delete went past it
                (x, y), (w, h) = dpg.get_item_pos(tag), dpg.get_item_state(tag).get("rect_size") or (0, 0)
                hit = x <= mx <= x + w and y <= my <= y + h
            if hit:
                self.focus = tag                      # a docked frame counts: Undo then goes to it
                break
        if self.layout == "graph" and not self.over_float():
            self.gp.on_press()

    def over_float(self):
        """The pointer on something floating over the panes - a frame, a
        dialog, the 3-D view or the properties over the graph: a press there
        is not the graph's, though a node lies under it (the graph finds the
        node under the pointer by its rectangle)."""
        mx, my = dpg.get_mouse_pos(local=False)
        return any(x0 <= mx <= x1 and y0 <= my <= y1 for x0, y0, x1, y1 in (getattr(self, "_holes", None) or ()))

    def on_mouse_release(self, sender, app_data):
        if shape_ui.release(self):
            return
        if shape_tools.release(self):                # a handle's drag kept, a box's parts selected
            return
        if room.release(self):
            return
        if self._sec_drag:
            key, target = self._sec_drag, self._sec_target
            self._sec_drag = self._sec_target = None
            self._ghost_end()
            if dpg.does_item_exist("snap_rect"):
                dpg.configure_item("snap_rect", show=False)
            if target:
                self.sec_move(key, *target)
            return
        if self._pane_drag:
            slot, target = self._pane_drag, self._pane_target
            self._pane_drag = self._pane_target = None
            self._ghost_end()
            if dpg.does_item_exist("snap_rect"):
                dpg.configure_item("snap_rect", show=False)
            if target:
                self.move_slot(slot, *target)
            return
        if self._split_drag:
            self._split_drag = None
            self.prefs["side_w"] = int(round(self.side_w / typeface.scale()))                 # at 100%, as laid out
            self.prefs["colw"] = self.colw
            self.prefs["rowh"] = self.rowh
            save_prefs(self.prefs)
        self._dragging = False
        self._pan_drag = None
        if self.layout == "graph":
            self.gp.on_release()

    def on_right_click(self, sender, app_data):
        if shape_tools.right(self):
            return                                       # a modal move put back, or a part's own menu
        if self.layout == "graph" and (dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)):
            if self.gp.knife_start():
                return                                   # Ctrl+right-drag: the knife, not the menu
        k = midi_ui.hovered_slider()
        if k and self.ui:
            midi_ui.slider_menu(self, k); return         # a parameter slider: MIDI learn, and what is on it
        for pane, tag in getattr(self, "pane_menus", {}).items():
            if pane == "side_win" and not any(dpg.is_item_hovered(f"sec_{k}_hdr") for k in self.SECTIONS
                                              if dpg.does_item_exist(f"sec_{k}_hdr")):
                continue                              # the panel's menu is its section headers'
            if dpg.does_item_exist(pane) and dpg.is_item_shown(pane) and dpg.is_item_hovered(pane) and self.ui:
                x, y = dpg.get_mouse_pos(local=False)
                dpg.configure_item(tag, show=True)
                dpg.set_item_pos(tag, [x, y])
                return
        if self.layout == "graph":
            self.gp.open_menu()

    def on_drag(self, sender, app_data):
        if shape_ui.drag(self):
            return
        if shape_tools.drag(self):
            return
        if room.drag(self):
            return
        if self._sec_drag:
            self._ghost_move()
            mx, my = dpg.get_mouse_pos(local=False)
            target = self.sec_zone(mx, my)
            if target and target[0] == self._sec_drag:
                target = None
            if target != self._sec_target:
                self._sec_target = target
                if dpg.does_item_exist("snap_rect"):
                    if target:
                        x0, y0, x1, y1 = self._sec_zone_rect(*target)
                        dpg.configure_item("snap_rect", pmin=(x0, y0), pmax=(x1, y1), show=True)
                    else:
                        dpg.configure_item("snap_rect", show=False)
            return
        if self._pane_drag:
            # the pane under the pointer lights up where the drop would go
            self._ghost_move()
            mx, my = dpg.get_mouse_pos(local=False)
            target = self.drop_zone(mx, my, frame=self._pane_drag in self.OPTIONAL)
            if target and target[0] == self._pane_drag:
                target = None
            if target != self._pane_target:
                self._pane_target = target
                if dpg.does_item_exist("snap_rect"):
                    if target:
                        x0, y0, x1, y1 = self._zone_rect(*target)
                        dpg.configure_item("snap_rect", pmin=(x0, y0), pmax=(x1, y1), show=True)
                    else:
                        dpg.configure_item("snap_rect", show=False)
            return
        if self._split_drag:
            tag, x0, v0 = self._split_drag
            mx, my = dpg.get_mouse_pos(local=False)
            vw = max(640, dpg.get_viewport_client_width())
            if tag == "help_split":
                new = int(max(20, min(240, v0 + (my - x0))))
                if new != int(pref_num(self.prefs, "help_h", 46)):
                    self.prefs["help_h"] = new
                    dpg.configure_item("graph_help_box", height=new)
                return
            if v0[0] == "side":
                _, sign, w0 = v0
                new = int(max(px(240), min(int(vw * 0.6), w0 + sign * (mx - x0))))
                if abs(new - dock.width(self)) >= 6:
                    dock.set_width(self, new); self.request_layout()
            elif v0[0] == "col":
                _, i, a, b = v0
                fw = max(1, self._free_w)
                lo = VIEW_MIN / fw
                d = max(lo - a, min(b - lo, (mx - x0) / fw))
                fr = self._col_fracs(self._cols)
                if abs((a + d) - fr.get(i, a)) * fw >= 4:
                    fr[i], fr[i + 1] = a + d, b - d
                    self.colw.setdefault(self.layout, {})[self._col_key(self._cols)] = [fr[k] for k in sorted(fr)]
                    self.request_layout()
            else:
                _, i, j, a, b = v0
                hs = max(1, self._rows_h[i] if i < len(self._rows_h) else 1)
                lo = (VIEW_MIN // 2) / hs
                d = max(lo - a, min(b - lo, (my - x0) / hs))
                rf = self._row_fracs(self._cols[i])
                if abs((a + d) - rf[j]) * hs >= 4:
                    rf[j], rf[j + 1] = a + d, b - d
                    self.rowh["+".join(self._cols[i])] = rf
                    self.request_layout()
            return
        if getattr(self, "_pan_drag", None) is not None:
            self.pan_by(app_data)
            return
        # Keyed to whether the drag STARTED on the cube, not to what is under
        # the pointer now, so running off the edge mid-turn does not drop it.
        if not self._dragging:
            return
        _, dx, dy = app_data
        # Scaled to the view, so dragging the full width is half a turn whatever
        # size the window is. A fixed radians-per-pixel means the same hand
        # movement does something different after you resize.
        k = 3.14159265 / max(120, self.view_side)
        view3d.orbit(self, self._yaw0 + dx * k, self._pitch0 + dy * k)

    def pan_by(self, app_data):
        """A drag with the pan held (middle, or Ctrl+left): the step since the last."""
        _, dx, dy = app_data
        last = self._pan_drag
        view3d.pan(self, dx - last[0], dy - last[1])
        self._pan_drag = [dx, dy]

    def on_mid_click(self, sender, app_data):
        if dpg.does_item_exist("cube_img") and dpg.is_item_hovered("cube_img"):
            self._pan_drag = [0.0, 0.0]              # middle-drag on the 3-D view pans it

    def on_mid_drag(self, sender, app_data):
        if getattr(self, "_pan_drag", None) is not None:
            self.pan_by(app_data)
            return
        self.gp.on_mid_drag((app_data[1], app_data[2]))

    def on_mid_release(self, sender, app_data):
        self._pan_drag = None
        self.gp.on_mid_release()

    def on_wheel(self, sender, app_data):
        if room.wheel(self, app_data):
            return                                       # Ctrl+wheel over the 3-D view in its corner: its size
        from native import sequence_ui
        if sequence_ui.wheel(self, app_data):
            return                                       # over the Sequence's timeline: along the time, Ctrl: a zoom
        if dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl):
            h = num.hovered()
            if h is not None:
                num.step(h, 1 if app_data > 0 else -1)   # Ctrl+wheel over a number field, anywhere: a step (num.py)
                return
        if self.layout == "edit" and self.code_ed is not None and dpg.does_item_exist("code_ed") and dpg.is_item_hovered("code_ed"):
            self.code_ed.wheel(app_data)
            return
        if self.layout == "graph" and dpg.does_item_exist("node_editor") and dpg.is_item_hovered("node_editor") \
                and not dpg.is_item_hovered("graph_menu") and not dpg.is_item_hovered("graph_ctx"):
            ctrl = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
            if ctrl and self.gp.step_hovered(app_data):
                return                                   # Ctrl+wheel over a dropdown steps it
            self.gp.zoom_step(app_data, dpg.get_mouse_pos(local=False))
            return
        if not dpg.is_item_hovered("cube_img"):
            return
        # Multiplicative, so a notch moves the same proportion at every range.
        view3d.zoom(self, app_data)

    TYPING = ("mvAppItemType::mvDragFloat", "mvAppItemType::mvDragInt",       # a number field typed into (num.py)
              "mvAppItemType::mvInputText", "mvAppItemType::mvInputInt", "mvAppItemType::mvInputFloat",
              "mvAppItemType::mvInputDouble", "mvAppItemType::mvInputIntMulti", "mvAppItemType::mvInputFloatMulti",
              "mvAppItemType::mvInputDoubleMulti", "mvAppItemType::mvSliderFloat", "mvAppItemType::mvSliderInt",
              "mvAppItemType::mvDragFloat", "mvAppItemType::mvDragInt")

    def typing(self):
        """True while a box somewhere has the keyboard: the focused item is
        an input (any frame's - the sequence's name, the library's search,
        a shape's size...) and active, or one of the boxes registered by
        hand. The key handler is global, so without this a letter typed
        into a name would also be a hotkey."""
        f = dpg.get_focused_item()
        if f and dpg.does_item_exist(f) and dpg.get_item_type(f) in self.TYPING and dpg.is_item_active(f):
            return True
        if num.any_active():                             # a number field typed into: not the focused item then
            return True
        return any(dpg.does_item_exist(t) and dpg.is_item_active(t)
                   for t in tuple(self._inputs) + ("find_text", "replace_text", "dev_add_host", "name_input", "editor_cmd") + self.META_FIELDS)

    def on_key(self, sender, app_data):
        if shape_tools.key(self, app_data):
            return                                       # a move, turn or scale under way has the keys: X Y Z, a number, Enter, Esc
        from native import sequence_ui
        if sequence_ui.key(self, app_data):
            return                                       # the sequence frame's own: Space, Delete, Ctrl+D
        # Enter in the add menu's search adds the first match. The box gives up the keyboard on Enter before this
        # handler runs (it is called after the frame), so "active" is already false: deactivated this frame counts.
        if (app_data in (dpg.mvKey_Return, dpg.mvKey_NumPadEnter) and dpg.does_item_exist("graph_search")
                and dpg.is_item_shown("graph_menu")
                and (dpg.is_item_active("graph_search") or dpg.is_item_deactivated("graph_search"))):
            self.gp._search_enter(None, dpg.get_value("graph_search"))
            return
        if app_data == dpg.mvKey_Escape:
            self._picker = None
            if dpg.does_item_exist("expr_win") and dpg.is_item_shown("expr_win"):
                dpg.configure_item("expr_win", show=False)   # the expression box, left
        # Presentation keys sit under the left hand so the right stays on the
        # mouse for rotating the cube: Q and E either side of W, which is the
        # pair together.
        # Not while a value is being typed. The handler is global, so without
        # this, typing into a box would also be driving the layout.
        if dpg.does_item_exist("palette_win") and dpg.is_item_shown("palette_win"):
            # the palette has every key while it is up: Esc closes, Up / Down choose a row, Enter runs it
            if app_data == dpg.mvKey_Escape:
                dpg.hide_item("palette_win")
            elif app_data in (dpg.mvKey_Return, dpg.mvKey_NumPadEnter):
                chrome.palette_enter(self)
            elif app_data in (dpg.mvKey_Down, dpg.mvKey_Up):
                chrome.palette_move(self, 1 if app_data == dpg.mvKey_Down else -1)
            return
        if self.layout == "edit" and self.code_ed is not None and self.code_ed.focus:
            ctrl_ = dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl)
            shift_ = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
            if self.code_ed.key(app_data, ctrl_, shift_):
                return
            if not ctrl_ and app_data not in (dpg.mvKey_F1, dpg.mvKey_F2, dpg.mvKey_F3, dpg.mvKey_F5, dpg.mvKey_F11, dpg.mvKey_F12):
                return                                   # plain keys are typing
        if app_data == dpg.mvKey_F3 and dpg.does_item_exist("find_text") and dpg.is_item_active("find_text"):
            self.run_action("find_prev" if (dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)) else "find_next")
            return
        if self.typing():
            return
        if dpg.does_item_exist("name_dialog") and dpg.is_item_shown("name_dialog"):
            if app_data == dpg.mvKey_Escape:
                dpg.hide_item("name_dialog")
            return
        if self.layout == "graph" and self.gp.typing():
            if app_data == dpg.mvKey_Return and dpg.does_item_exist("graph_search") and dpg.is_item_active("graph_search"):
                self.gp._search_enter(None, dpg.get_value("graph_search"))
            elif app_data == dpg.mvKey_Escape:
                self.gp._hide_menus()
            return
        # A key waited for by the shortcuts dialog takes it, whatever it is.
        binding = key_combo(app_data)
        if self._capture:
            if app_data == dpg.mvKey_Escape:
                self._capture = None
                chrome.refresh_keys(self)
            elif binding:
                self.keys.set(self._capture, binding)
                self._capture = None
                chrome.refresh_keys(self)
            return
        if app_data == dpg.mvKey_Escape and device_ui.focused_frame(self):
            device_ui.close(self, device_ui.focused_frame(self)); return    # Esc closes the floating frame with the focus
        if app_data == dpg.mvKey_Escape and chrome.focused_dialog() and chrome.focused_dialog() not in (reader_ui.TAG, "palette_win"):
            chrome.close_dialog(chrome.focused_dialog()); return          # ... and the dialog with the focus, as a frame
        if app_data == dpg.mvKey_Escape and dpg.does_item_exist("stats_pop") and dpg.is_item_shown("stats_pop"):
            dpg.hide_item("stats_pop"); return                            # the footer's figures, away
        if app_data == dpg.mvKey_Escape and not self.ui:
            self.leave_presentation(); return                             # the way out the hint names
        if reader_ui.key(self, app_data, binding):
            return                                       # the help window has the keyboard: Esc, find, back
        if self.layout == "graph" and app_data == dpg.mvKey_Back and self.gp.reset_hovered():
            return                                       # Backspace over a value: its default
        if self.layout == "graph" and binding is None:
            return
        if self.layout == "graph":
            # Nudging is not a binding: four keys, two steps, always these.
            shift = dpg.is_key_down(dpg.mvKey_LShift) or dpg.is_key_down(dpg.mvKey_RShift)
            step = 1 if shift else 10
            arrows = {dpg.mvKey_Left: (-step, 0), dpg.mvKey_Right: (step, 0),
                      dpg.mvKey_Up: (0, -step), dpg.mvKey_Down: (0, step)}
            alt = dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt)
            if app_data in arrows and not alt:
                self.gp.nudge(*arrows[app_data]); return
        if binding and self.over_view():
            va = self.keys.lookup(binding, "view")               # the 3-D view's own keys, with the pointer on it
            if va and self.keys.context.get(va) == "view" and shape_ui.view_key_ok(self, va):
                self.run_action(va)
                return
        action = self.keys.lookup(binding, "graph" if self.layout == "graph" else "global") if binding else None
        if action and len(binding) == 1 and not self.over_canvas():
            # A plain key - a letter, a digit, a sign - acts where the work is: over the views, over the graph,
            # or anywhere while presenting. From the panel, a frame or the code pane a stray one did whatever
            # it was bound to (H hid every control), so it says so instead (the critique's C13).
            messages.post(self, f"{binding} works with the pointer over the views or the graph", merge="stray-key")
            return
        if action:
            self.run_action(action)

    def over_view(self):
        """The pointer on the 3-D view - in its pane, in its corner of the
        graph, or full frame: its own keys (the camera's; the shape
        editor's) apply there. (The test hooks hold it true for a moment.)"""
        if time.time() < getattr(self, "_view_hold", 0.0):
            return True
        if time.time() < getattr(self, "_panel_hold", 0.0) or time.time() < getattr(self, "_canvas_hold", 0.0):
            return False                                     # the hooks' pointer on the panel or the graph, wherever the real one is
        return dpg.does_item_exist("cube_win") and dpg.is_item_shown("cube_win") and dpg.is_item_hovered("cube_win")

    def over_canvas(self):
        """The pointer over what a plain key is for: the logical view, the
        3-D view (in its corner of the graph too) or the graph - not a
        window over them - or anywhere while presenting. (The test hooks
        hold it true for a moment: they have no pointer.)"""
        if not self.ui or time.time() < getattr(self, "_canvas_hold", 0.0):
            return True
        if time.time() < getattr(self, "_panel_hold", 0.0):
            return False                                     # the hooks' pointer on the panel, wherever the real one is
        for tag in ("node_editor", "net_win", "cube_win"):
            if dpg.does_item_exist(tag) and dpg.is_item_shown(tag) and dpg.is_item_hovered(tag):
                return True
        return False

    def run_action(self, action):
        """Every keyboard action by name; the menus and toolbar call the same."""
        gp = self.gp
        table = {
            "view_net":     lambda: self.set_layout("net"),
            "view_cube":    lambda: self.set_layout("cube"),
            "view_both":    lambda: self.set_layout("both"),
            "pane_code":    lambda: self.toggle_pane("edit"),
            "pane_graph":   lambda: self.toggle_pane("graph"),
            "presentation": self.toggle_ui,
            "fullscreen":   dpg.toggle_viewport_fullscreen,
            "side_panel":   self.toggle_side,
            "props_pane":   self.toggle_props,
            "play_pause":   self.toggle_play,
            "step":         self.step_once,
            "speed_down":   lambda: self.step_speed(-1),
            "speed_up":     lambda: self.step_speed(1),
            "speed_reset":  lambda: self.set_speed(1.0),
            "restart":      lambda: self.eng.select(self.eng.idx),
            "prev_effect":  lambda: self.step_effect(-1),
            "next_effect":  lambda: self.step_effect(1),
            "prev_palette": lambda: self.step_palette(-1),
            "next_palette": lambda: self.step_palette(1),
            "live":         lambda: gp.set_auto(not gp.auto),
            "build":        self.build_current,
            "new":          self.new_effect,
            "open":         lambda: chrome.show_open(self),
            "save":         self.save_current,
            "rename":       self.rename_current,
            "import":       self.toggle_import_current,
            "find":         self.focus_find,
            "find_next":    lambda: self.code_ed and (self._find_setup(), self.code_ed.find_next(), self.find_status()),
            "find_prev":    lambda: self.code_ed and (self._find_setup(), self.code_ed.find_next(True), self.find_status()),
            "external":     self.open_external,
            "screenshot":   lambda: setattr(self, "shot_req", True),
            "record":       lambda: self.start_rec(15.0),
            "record_video": lambda: self.start_rec(15.0, "mp4"),
            "shortcuts":    lambda: chrome.show_keys(self),
            "guide":        lambda: reader_ui.open_doc(self, "GUIDE.md"),
            "tutorial":     lambda: reader_ui.open_doc(self, "TUTORIAL.md"),
            "tutorial_tree": lambda: reader_ui.open_doc(self, "TUTORIAL.md", "Tutorial 2: a Christmas tree in 3-D"),
            "node_ref":     lambda: reader_ui.open_doc(self, "NODES.md"),
            "node_help":    gp.help_here,
            "node_costs":   gp.measure_costs,
            "welcome":      lambda: reader_ui.show_welcome(self),
            "graph_room":   lambda: room.set_on(self, not room.on(self)),
            "graph_panel":  lambda: room.toggle_panel(self),
            "pip":          lambda: room.set_tucked(self, not room.pip(self)["tucked"]),
            "flash":        lambda: chrome.show_flash(self),
            "push":         self.push_settings,
            "stream":       lambda: self.stream_stop() if getattr(self, "ddp", None) is not None else self.stream_start(),
            "devices":      lambda: device_ui.show(self, "devices"),
            "send_frame":   lambda: device_ui.show(self, "send"),
            "shape":        lambda: device_ui.show(self, "shape"),
            "sequence":     lambda: device_ui.show(self, "sequence"),
            "library":      lambda: device_ui.show(self, "library"),
            "palettes":     lambda: device_ui.show(self, "palettes"),
            "vj":           lambda: device_ui.show(self, "vj"),
            "outputs":      lambda: device_ui.show(self, "outputs"),
            "audioin":      lambda: device_ui.show(self, "audioin"),
            "randomise":    self.randomise,
            "undo":         lambda: self.undo_where(),
            "redo":         lambda: self.undo_where(redo=True),
            "cut":          gp.cut,
            "copy":         gp.copy,
            "paste":        gp.paste,
            "duplicate":    self.duplicate_selected,
            "delete":       gp.delete_selected,
            "add_node":     self.search_nodes,
            "connect":      gp.connect_selected,
            "mute":         lambda: gp.toggle_selected("muted"),
            "collapse":     lambda: gp.toggle_selected("collapsed"),
            "hide_pins":    lambda: gp.toggle_selected("hide_pins"),
            "fold":         lambda: chrome.ask(self, "Sub-graph", "a name for the new node type", "",
                                               lambda v: gp.make_sub_from_selection(v)),
            "enter_sub":    self.enter_or_back,
            "arrange":      gp.arrange,
            "space_out":    gp.space_out,
            "align_left":   lambda: gp.align("left"),
            "align_right":  lambda: gp.align("right"),
            "align_top":    lambda: gp.align("top"),
            "align_bottom": lambda: gp.align("bottom"),
            "distribute_x": lambda: gp.distribute("x"),
            "distribute_y": lambda: gp.distribute("y"),
            "zoom_in":      lambda: gp.zoom_step(1),
            "zoom_out":     lambda: gp.zoom_step(-1),
            "zoom_reset":   lambda: gp.set_zoom(1.0),
            "frame_all":    gp.home,
            "stop_preview": gp.stop_preview,
            "focus_mode":   lambda: gp.set_focus_mode(not gp.focus_mode),
            "wire_light":   lambda: gp.set_wire_light(not gp.wire_light()),
            "unlit_dots":   lambda: self.set_view_option("unlit_dots"),
            "view_floor":   lambda: self.set_view_option("view_floor"),
            "view_front":   lambda: view3d.preset(self, "front"),
            "view_back":    lambda: view3d.preset(self, "back"),
            "view_side":    lambda: view3d.preset(self, "right"),
            "view_left":    lambda: view3d.preset(self, "left"),
            "view_top":     lambda: view3d.preset(self, "top"),
            "view_below":   lambda: view3d.preset(self, "below"),
            "view_iso":     lambda: view3d.preset(self, "isometric"),
            "view_ortho":   lambda: view3d.toggle_ortho(self),
            "view_frame":   lambda: shape_ui.frame_selection(self),
            "view_home":    lambda: view3d.home(self),
            "shape_move":   lambda: shape_tools.start(self, "move"),
            "shape_turn":   lambda: shape_tools.start(self, "turn"),
            "shape_scale":  lambda: shape_tools.start(self, "scale"),
            "shape_dup":    lambda: shape_tools.duplicate(self),
            "shape_delete": lambda: shape_tools.delete(self),
            "shape_all":    lambda: shape_tools.select_all(self),
            "minimap":      lambda: room.set_minimap(self, show=not self.prefs.get("minimap", True)),
            "select_all":   gp.select_all,
            "select_none":  gp.select_none,
            "select_invert": gp.select_invert,
            "select_up":    lambda: gp.select_linked("up"),
            "select_down":  lambda: gp.select_linked("down"),
            "select_linked": lambda: gp.select_linked("both"),
            "frame_selected": gp.frame_selected,
            "snap":         gp.toggle_snap,
            "dissolve":     gp.dissolve_selected,
            "disconnect":   gp.disconnect_selected,
            "swap_inputs":  gp.swap_inputs,
            "label_node":   gp.label_selected,
            "frame_sel":    lambda: gp.frame_selection(),
            "repeat":       self.repeat_last,
            "palette":      lambda: chrome.show_palette(self),
            "snapshots":    lambda: chrome.show_snapshots(self),
            "expr":         lambda: gp.expr_hovered(),
            "midi":         lambda: midi_ui.show(self),
            "bank":         lambda: bank_ui.show(self),
            "undo_history": lambda: chrome.show_undo_history(self),
            "history":      lambda: chrome.show_history(self),
            "compare":      lambda: self.stop_ab() if self.ab else chrome.show_compare(self),
            "script_preview": self.preview_script,
            "script_send":  self.send_script,
            "sweep":        lambda: self.stop_sweep() if self.sweep else chrome.show_sweep(self),
        }
        fn = table.get(action)
        if fn and not weight.enabled(self, action) and action not in ("undo", "redo"):
            self.gp.status(weight.WHY.get(weight.NEEDS[action], "not now"))     # greyed on the menus: say why
            return
        if fn:
            if action not in ("repeat", "palette", "undo_history", "undo", "redo"):
                self._last_action = action
            fn()

    def docked_tags(self):
        """The windows of the frames in the dock now."""
        return tuple(tag for slot, (tag, _, _, _) in device_ui.FRAMES.items() if self.docked(slot))

    def undo_target(self):
        """What Undo acts on: the frame with the keyboard (floating, or
        docked and last clicked in) - the shape, the sequence, the
        palettes - else the code pane, else the graph."""
        f = device_ui.focused_frame(self)
        if f is None and view3d.editing(self) and self.over_view():
            f = "shape"                                  # the pointer on the 3-D view while a shape is built: its steps
        if f is None:
            for slot, (tag, _, _, _) in device_ui.FRAMES.items():
                if self.focus == tag and self.docked(slot):
                    f = slot; break
        if f in ("shape", "sequence", "palettes", "vj"):
            return f
        return "code" if self.layout == "edit" else "graph"

    def undo_where(self, redo=False):
        t = self.undo_target()
        if t == "shape":
            from native import shape_ui
            shape_ui.redo(self) if redo else shape_ui.undo(self)
        elif t == "sequence":
            from native import sequence_ui
            sequence_ui.undo(self, redo)
        elif t == "palettes":
            from native import palette_ui
            palette_ui.undo(self, redo)
        elif t == "vj":
            from native import vj_ui
            vj_ui.undo(self, redo)
        elif t == "code":
            self.code_redo() if redo else self.code_undo()
        else:
            self.gp.redo() if redo else self.gp.undo()

    def repeat_last(self):
        a = getattr(self, "_last_action", None)
        if a:
            self.run_action(a)
        else:
            self.gp.status("nothing to repeat yet")
