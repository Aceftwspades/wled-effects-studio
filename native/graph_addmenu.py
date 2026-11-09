"""The add-node menu - a mixin of graph_ui's GraphPanel: opened at the pointer or on a pin, its search, the node types listed by category with favourites and recent picks, a hovered type described beside the list, and the node added where the menu was."""
import dearpygui.dearpygui as dpg
from native.typeface import px
from native import typeface
from native import weight
from native import nodeface
from native.graph import compatible          # the one rule for what may feed what
from native import graph_ui as GU


class GraphAddMenu:
    # --- the right-click menus -------------------------------------------------------------
    def open_menu(self):
        """Right click: over a pin, the pin's menu; over a node, the node's;
        over empty editor, the add-node menu at the pointer."""
        if not dpg.does_item_exist("node_editor") or not dpg.is_item_hovered("node_editor"):
            return
        mx, my = dpg.get_mouse_pos(local=False)
        for (nid, kind, name), tag in self._pins.items():
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._ctx = (kind, nid, name)
                self._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [mx, my])
                return
        for nid in list(self.graph.nodes) if self.graph else []:
            tag = f"gnode_{nid}"
            if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                self._ctx = ("node", nid, None)
                self._fill_ctx_menu()
                dpg.configure_item("graph_ctx", show=True); dpg.set_item_pos("graph_ctx", [mx, my])
                return
        gx, gy = self._to_graph((mx, my))
        self._menu_pos = (gx - 20, gy - 10)
        self._pending = None
        self.show_add_menu((mx, my))

    def show_add_menu(self, at, only=None, focus=True):
        """The add menu at a screen position, its search box focused and
        empty. `only` narrows it to those node types (a dropped wire)."""
        self._only = only
        self._fill_quick()
        self._desc_hint()
        dpg.set_value("graph_search", "")
        self._search("graph_search", "")
        dpg.configure_item("graph_menu", show=True)
        dpg.set_item_pos("graph_menu", list(at))
        if focus:
            dpg.focus_item("graph_search")

    def _search(self, sender, text):
        """Filter the add menu: with text, a flat list of matches on name or
        description; without, the categories (or the dropped wire's list)."""
        text = (text or "").strip().lower()
        only = getattr(self, "_only", None)
        flat = bool(text) or only is not None
        dpg.configure_item("graph_cats", show=not flat)
        dpg.configure_item("graph_hits", show=flat)
        if not flat:
            return
        dpg.delete_item("graph_hits", children_only=True)
        self._menu_entries_cache = None
        names = only if only is not None else [n.split(" / ", 1)[1] for n in self.type_names()]
        names = [n for n in names if not self._feature_off(n)]
        if only is None:
            names = ["preset:" + p for p in sorted(self.presets())] + names
        hits = []
        for n in names:
            d = self.lib.get(n, {})
            lbl = d.get("label", n) if not n.startswith("preset:") else n[7:] + "  (preset)"
            if not text or text in lbl.lower() or text in n.lower() or text in d.get("doc", "").lower():
                hits.append((0 if text and lbl.lower().startswith(text) else 1, lbl, n))
        if text:
            hits.sort()                    # else the given order: most useful first
        if only is not None and not text:
            dpg.add_text("connect to a new", parent="graph_hits", color=GU.DIM)
        for _, lbl, n in hits[:24]:
            dpg.add_selectable(label=lbl, parent="graph_hits", user_data=n,
                               callback=lambda s, a, u: self.add_node_at_menu(u))
        if not hits:
            dpg.add_text("no match", parent="graph_hits", color=GU.DIM)
        rows = min(len(hits), 24) + (1 if only is not None and not text else 0)
        dpg.configure_item("graph_hits", height=max(30, 21 * max(rows, 1) + 12))
        if hits:                                          # what Enter would add, until the pointer rests on another
            self._add_preview = hits[0][2]
            self.describe_type(hits[0][2])

    def _search_enter(self, sender, text):
        """Enter in the search box adds the first hit."""
        kids = dpg.get_item_children("graph_hits", 1) or []
        for k in kids:
            u = dpg.get_item_user_data(k)
            if u:
                self.add_node_at_menu(u)
                return

    def fill_add_menu(self):
        """The right-click add menu, rebuilt whenever the library changes so
        new sub-graphs appear in it."""
        if not dpg.does_item_exist("graph_menu"):
            return
        dpg.delete_item("graph_menu", children_only=True)
        cats = {}
        for name in self.type_names():
            c, n = name.split(" / ", 1)
            cats.setdefault(c, []).append(n)
        # two columns: the list, and beside it what the node under the pointer does. In the menu itself, so the
        # pointer goes straight across to it and the wheel scrolls it: in the properties over the canvas it was cut
        # short, out of the pointer's reach while the menu was up, and the first time it came up it took the focus
        # and closed the menu
        row = dpg.add_group(horizontal=True, parent="graph_menu")
        dpg.add_group(tag="graph_menu_list", parent=row)
        dpg.add_input_text(tag="graph_search", parent="graph_menu_list", hint="search nodes", width=px(200),
                           callback=self._search, on_enter=False)
        # on_enter would stop the per-keystroke callback; Enter is read separately
        dpg.add_text("add node", parent="graph_menu_list", color=GU.DIM)
        # child windows rather than groups: a collapsing header stretches to
        # its parent, and an autosized popup would stretch with it
        dpg.add_child_window(tag="graph_hits", parent="graph_menu_list", show=False, width=px(230), height=px(60),
                             border=False)
        dpg.add_child_window(tag="graph_desc", parent=row, width=px(330), height=px(480), border=True)
        with dpg.child_window(tag="graph_cats", parent="graph_menu_list", width=px(230), height=px(430), border=False):
            # the last few added and the starred ones sit on top; refilled each open
            dpg.add_group(tag="graph_quick")
            self._fill_quick()
            pre = self.presets()
            if pre:
                with dpg.collapsing_header(label="presets", default_open=True):
                    for name in sorted(pre):
                        with dpg.group(horizontal=True):
                            dpg.add_selectable(label=name, user_data="preset:" + name, width=px(180),
                                               callback=lambda s, a, u: self.add_node_at_menu(u))
                            dpg.add_button(label="x", small=True, user_data=name,
                                           callback=lambda s, a, u: self.delete_preset(u))
                            weight.danger(dpg.last_item())
            hidden = 0
            for c, names in cats.items():
                with dpg.collapsing_header(label=c, default_open=(c in ("generate", "colour", "subgraphs"))) as hdr:
                    if self.app.prefs.get("cat_colours", True):
                        dpg.bind_item_theme(hdr, self._cat_header_theme(c))
                    for n in names:
                        if self._feature_off(n):
                            hidden += 1
                            continue
                        lbl = self.lib[n].get("label", n) if n in self.lib else n
                        dpg.add_selectable(label=lbl, user_data=n,
                                           callback=lambda s, a, u: self.add_node_at_menu(u))
            if hidden:
                dpg.add_text(f"{hidden} node(s) hidden: their feature is off in Flash > Features", color=GU.DIM, wrap=0)
        self._widgets.add("graph_search")
        self._desc_hint()

    # --- a node hovered in the add menu is described beside the list ----------------------
    def _desc_hint(self):
        """The description column before a node is under the pointer."""
        self._add_preview = None
        if dpg.does_item_exist("graph_desc"):
            dpg.delete_item("graph_desc", children_only=True)
            dpg.add_text("rest the pointer on a node to read what it does - its pins and its settings",
                         parent="graph_desc", color=GU.DIM, wrap=0)

    def _fit_add_menu(self):
        """The description column as tall as the list beside it (the list
        grows with a search's hits), and the menu - opened at the pointer,
        and wide with its description - kept inside the window."""
        if dpg.does_item_exist("graph_menu_list") and dpg.does_item_exist("graph_desc"):
            lh = int(dpg.get_item_rect_size("graph_menu_list")[1])
            want = max(lh, px(300))
            if lh > 0 and abs(dpg.get_item_height("graph_desc") - want) > 1:
                dpg.configure_item("graph_desc", height=want)
        w, h = dpg.get_item_rect_size("graph_menu")
        if w <= 0 or h <= 0:
            return
        x, y = dpg.get_item_pos("graph_menu")
        vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        nx, ny = max(0, min(x, vw - w - 4)), max(0, min(y, vh - h - 4))
        if (nx, ny) != (x, y):
            dpg.set_item_pos("graph_menu", [int(nx), int(ny)])
    def _menu_entries(self):
        """Every selectable in the add menu, with the type it adds."""
        out = []
        def walk(item):
            for k in dpg.get_item_children(item, 1) or []:
                if not dpg.does_item_exist(k):
                    continue
                if dpg.get_item_type(k).endswith("::mvSelectable") and dpg.get_item_user_data(k):
                    out.append(k)
                else:
                    walk(k)
        for root in ("graph_hits", "graph_cats"):
            if dpg.does_item_exist(root):
                walk(root)
        return out

    def _poll_add_preview(self):
        """While the add menu is up, the node under the pointer is described
        in its column beside the list - and stays while the pointer goes
        across to read it (nothing is under the pointer on the way)."""
        if not dpg.does_item_exist("graph_menu") or not dpg.is_item_shown("graph_menu"):
            if self._add_preview is not None:
                self._add_preview = None
                self._menu_entries_cache = None
            return
        self._fit_add_menu()
        if self._menu_entries_cache is None:
            self._menu_entries_cache = self._menu_entries()
        hovered = None
        for k in self._menu_entries_cache:
            if dpg.does_item_exist(k) and dpg.is_item_hovered(k):
                hovered = dpg.get_item_user_data(k); break
        if hovered is None or hovered == self._add_preview:
            return
        self._add_preview = hovered
        self.describe_type(hovered)

    def describe_type(self, type_):
        """A node type in the add menu's description column: what it is,
        its pins and settings, each with its words."""
        P = "graph_desc"
        if not dpg.does_item_exist(P):
            return
        dpg.delete_item(P, children_only=True)
        dpg.set_y_scroll(P, 0.0)
        if type_.startswith("preset:"):
            typeface.heading(dpg.add_text(f"preset: {type_[7:]}", parent=P))
            dpg.add_text("a node saved with its settings, from a node's menu", parent=P, color=GU.DIM, wrap=0)
            return
        d = self.lib.get(type_)
        if not d:
            return
        typeface.heading(dpg.add_text(d.get("label") or type_, parent=P, wrap=0))
        typeface.small(dpg.add_text(f"{d.get('cat', '')} - runs per {d.get('scope', 'pixel')}", parent=P, color=GU.DIM))
        if d.get("doc"):
            dpg.add_text(d["doc"], parent=P, wrap=0)
        for title, items in (("inputs", d.get("inputs", [])), ("outputs", d.get("outputs", [])), ("settings", d.get("params", []))):
            if not items:
                continue
            typeface.label(dpg.add_text(title.upper(), parent=P, color=GU.DIM))
            lines = []
            for p in items:
                shown = nodeface.label(type_, p["name"])
                line = f"  {shown}" + (f" [{p['name']}]" if shown != p["name"] else "") + f" ({p.get('type', '')})"
                if p.get("doc"):
                    line += f": {p['doc']}"
                lines.append(line)
            # one block a list: its lines as close as a paragraph's (a text each had the theme's gap between them)
            dpg.add_text("\n".join(lines), parent=P, wrap=0)

    def _fill_quick(self):
        """Favourites (starred in a node's menu) and the recently added, at
        the top of the add menu."""
        if not dpg.does_item_exist("graph_quick"):
            return
        dpg.delete_item("graph_quick", children_only=True)
        self._menu_entries_cache = None
        favs = [n for n in self.app.prefs.get("fav_nodes", []) if n in self.lib]
        rec = [n for n in self.app.prefs.get("recent_nodes", []) if n in self.lib and n not in favs]
        for title, names in (("favourites", favs), ("recent", rec)):
            if not names:
                continue
            with dpg.collapsing_header(label=title, default_open=True, parent="graph_quick"):
                for n in names:
                    dpg.add_selectable(label=self.lib[n].get("label", n), user_data=n,
                                       callback=lambda s, a, u: self.add_node_at_menu(u))

    def _note_recent(self, type_):
        if type_ not in self.lib or self.lib[type_].get("decor"):
            return
        rec = [n for n in self.app.prefs.get("recent_nodes", []) if n != type_]
        self.app.prefs["recent_nodes"] = ([type_] + rec)[:6]
        from native.project import save_prefs
        save_prefs(self.app.prefs)

    def toggle_favourite(self, type_):
        favs = list(self.app.prefs.get("fav_nodes", []))
        if type_ in favs:
            favs.remove(type_); self.status(f"{type_}: no longer a favourite")
        else:
            favs.append(type_); self.status(f"{type_}: a favourite, at the top of the add menu")
        self.app.prefs["fav_nodes"] = favs
        from native.project import save_prefs
        save_prefs(self.app.prefs)

    def _hide_menus(self):
        for t in ("graph_menu", "graph_ctx"):
            if dpg.does_item_exist(t):
                dpg.configure_item(t, show=False)

    def add_node_at_menu(self, type_):
        self.touch()
        dpg.configure_item("graph_menu", show=False)
        if not self.graph:
            return
        if self._pending and self._pending[0] == "replace":     # change a node's type: the pick replaces it
            _, old = self._pending
            self._pending = None
            if type_ in self.lib and old in self.graph.nodes:
                self.change_type(old, type_)
            return
        if type_.startswith("preset:"):
            nid = self.add_preset(type_[7:], self._menu_pos)
            if nid is None:
                return
            type_ = self.graph.nodes[nid]["type"]
        elif type_ not in self.lib:
            return
        else:
            self.snapshot()
            nid = self.graph.add(type_, self._menu_pos)
            self._make_node(nid, self.graph.nodes[nid])
            self._note_recent(type_)
        if type_ == "Frame":
            self._sync_pos(); self.rebuild()      # behind the nodes it now covers
        if self._pending and self._pending[0] == "into":
            _, b, inp, t = self._pending
            self._pending = None
            d = self.graph.node_def(self.graph.nodes[nid])
            out = next((o["name"] for o in d["outputs"] if compatible(o["type"], t)), None)
            if out and b in self.graph.nodes:
                self.graph.link(nid, out, b, inp)
                self.rebuild()
        elif self._pending:
            a, out, t = self._pending
            self._pending = None
            d = self.graph.node_def(self.graph.nodes[nid])
            inp = next((i["name"] for i in d["inputs"] if compatible(t, i["type"])), None)
            if inp and a in self.graph.nodes:
                self.graph.link(a, out, nid, inp)
                self.rebuild()

    def add_node(self, type_):
        self.touch()
        if not self.graph or type_ not in self.lib:
            return
        self.snapshot()
        self._add_count += 1
        pos = (60 + 30 * (self._add_count % 8), 60 + 30 * (self._add_count % 8))
        nid = self.graph.add(type_, pos)
        self._make_node(nid, self.graph.nodes[nid])
        return nid
