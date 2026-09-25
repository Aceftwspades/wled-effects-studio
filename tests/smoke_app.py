"""Drive the running app through its main flows and fail on any traceback.

The app takes commands from a JSON file (native/app.py service_command),
which is how every panel here was checked without a hand on the mouse.
This launches the app, walks the layouts, opens a graph and a code effect,
exercises the editor, segments, A/B, sweep, the script preview, the
dialogs and the keys, then reads the app's log for tracebacks.

    python tests/smoke_app.py          # from studio; ~60 s; exits 1 on a traceback

It is deliberately not a pytest: it needs the window, the engine and a
minute; run it before a release, not on every save.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# STUDIO_EXE: the packaged app's exe to test instead of the tree - its
# folder is then the home (projects/, build/) the test saves and restores
EXE = os.environ.get("STUDIO_EXE")
ROOT = os.path.dirname(os.path.abspath(EXE)) if EXE else os.path.dirname(HERE)
CMD = os.path.join(tempfile.gettempdir(), "cubefx", "command.json")
LOG = os.path.join(tempfile.gettempdir(), "cubefx", "smoke.log")

STEPS = [
    ([{"layout": "both"}, {"effect": "Maelstrom"}], 1.5),
    # a graph compiled and built: the toolchain works (the bundled one in a packaged run) and box_fire.cpp exists for the code steps
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"py": "app.gp.compile()"}], 20.0),
    ([{"expect": ["edit_status", "loaded cubefx_"]}, {"key": "Home"}, {"speed": 0.5},
      # a typed value poked into the running effect's parameter table: no rebuild
      {"py": "(app.eng.names[app.eng.idx], (lambda k: app.gp.live_poke(k[0], k[1], 0.42))(next(iter(app.gp._live))))"}], 1.5),
    ([{"expect": ["stat_txt", "speed 1/2x"]}, {"action": "speed_up"}, {"action": "speed_up"}, {"action": "speed_up"}], 1.0),
    ([{"expect": ["stat_txt", "speed 4x"]}, {"action": "speed_reset"}, {"layout": "both"}], 0.8),
    # the LED under a point of the net and of the 3-D view, by wiring index
    ([{"py": "app.led_at(*[a + b * 0.5 for a, b in zip(dpg.get_item_state('net_img')['rect_min'], dpg.get_item_state('net_img')['rect_size'])])"},
      {"py": "app.led_at(*[a + b * 0.5 for a, b in zip(dpg.get_item_state('cube_img')['rect_min'], dpg.get_item_state('cube_img')['rect_size'])])"}], 0.5),
    # an XY pad on a Transform node: a point on it sets both inputs (pivot 0..1), the fields follow; undone
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"py": "app.gp.graph.add('Transform', (60, 60))"}, {"py": "app.gp.rebuild()"},
      {"graph_zoom": 1.0}, {"pad": [0, 0.25, 0.75]}], 1.0),
    ([{"py": "dpg.get_value(f'gin_{max(app.gp.graph.nodes)}_pivot_u_w')"}, {"graph_undo": True}, {"graph_undo": True}], 0.5),
    # modulation as a gesture: an LFO onto a typed value, then the beat's hit; undone
    ([{"graph_open": "box_fire.json"}, {"py": "app.gp.modulate(next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Noise'), 'scale', ('lfo', 'value', {}))"}], 1.0),
    ([{"expect": ["messages", "modulated by Wave"]}, {"graph_undo": True}], 0.5),
    # snapshots: the look saved twice with a typed value changed between, the morph half way (live), the window shown
    ([{"graph_open": "box_fire.json"}, {"snap": ["save", "smoke A"]},
      {"py": "app.gp.graph.nodes[next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Noise')]['inputs'].__setitem__('scale', 9.0)"},
      {"snap": ["save", "smoke B"]}, {"snap": ["morph", "smoke A", "smoke B", 0.5]}, {"chrome": "snapshots"}], 1.5),
    ([{"expect": ["messages", "smoke A"]}, {"py": "dpg.hide_item('snap_win')"}, {"snap": ["del", "smoke A"]}, {"snap": ["del", "smoke B"]}], 0.5),
    # a Bitmap painted in the properties pane: one cell set, the rows follow, undone
    ([{"layout": "graph"}, {"graph_open": "question_block.json"},
      {"py": "setattr(app.gp, '_test_sel', [next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Bitmap')])"}], 0.8),
    ([{"paint": [0, 0, 7]}, {"py": "app.gp._bitmap_ed is not None"}, {"graph_selected": []}, {"graph_undo": True}], 0.8),
    # Home fits the whole graph by the view alone: the zoom changes, no node's saved place does, no undo step
    ([{"graph_open": "box_fire.json"}, {"graph_zoom": 1.0}, {"py": "setattr(app, '_home_before', (dict((k, list(n['pos'])) for k, n in app.gp.graph.nodes.items()), len(app.gp._undo)))"},
      {"key": "Home"}], 1.0),
    ([{"check": "app.gp.zoom < 1.0"}, {"check": "all(list(n['pos']) == app._home_before[0][k] for k, n in app.gp.graph.nodes.items())"},
      {"check": "len(app.gp._undo) == app._home_before[1]"}, {"expect": ["messages", "the whole graph"]}, {"graph_zoom": 1.0}], 0.5),
    # the face of a node: a collapsed node's body is what it computes, the line follows a typed value, a stand-in
    # carries it too; the zoom scales the nodes themselves (a 50% node is half as tall); category hues on the titles
    ([{"graph_open": "box_fire.json"}, {"graph_zoom": 1.0}, {"py": "app.gp._collapse(11)"}], 1.0),
    ([{"expect": ["gsum_11", "a × 2"]}, {"py": "app.gp.set_input_live(11, 'b', 3.0)"}], 0.5),
    ([{"expect": ["gsum_11", "a × 3"]}, {"check": "dpg.get_item_rect_size('gnode_13')[1] > 90"}, {"graph_zoom": 0.5}], 1.0),
    ([{"check": "40 < dpg.get_item_rect_size('gnode_13')[1] < 70"}, {"py": "app.gp.set_overview_zoom(0.5)"}, {"graph_zoom": 0.4}], 1.0),
    ([{"expect": ["gsum_12", "scale"]}, {"check": "app.gp._standin_line.get(12, 0) > 0"},
      {"py": "app.gp.set_overview_zoom(0.0)"}, {"graph_zoom": 1.0}, {"graph_undo": True}, {"graph_undo": True}], 1.0),
    ([{"check": "app.gp.summary(12).startswith('scale ')"}, {"py": "app.prefs.__setitem__('cat_colours', False) or app.gp.rebind_themes()"},
      {"py": "app.prefs.__setitem__('cat_colours', True) or app.gp.rebind_themes()"}], 0.5),
    # the thin ones fleshed out: an expression into a typed input and a setting (x, the node's own numbers, the
    # maths functions; a refusal in the status), a modulator's range under the pin it feeds (Ctrl+wheel nudges an
    # end), the speed factor measured against the fake device
    ([{"graph_open": "box_fire.json"}, {"py": "app.gp.graph.nodes[13]['inputs'].__setitem__('b', 0.5)"},
      {"expr": [13, "b", "input", "x * 2 + sqrt(4)"]}, {"expr": [9, "out_hi", "param", "out_lo + pi/10"]},
      {"expr": [9, "out_lo", "param", "nope(1)"]}], 0.8),
    ([{"check": "abs(app.gp.graph.nodes[13]['inputs']['b'] - 3.0) < 1e-6"},
      {"check": "abs(app.gp.graph.nodes[9]['params']['out_hi'] - (app.gp.graph.nodes[9]['params']['out_lo'] + 0.3141592653589793)) < 1e-6"},
      {"expect": ["messages", "the functions here"]}, {"py": "app.gp.expr_for(13, 'b', 'input')"}], 0.6),
    ([{"check": "dpg.is_item_shown('expr_win')"}, {"key": "Escape"}, {"py": "app.gp.modulate(13, 'b', ('lfo', 'value', {}))"},
      {"py": "app.gp.set_selection([13])"}, {"action": "frame_selected"}, {"graph_zoom": 1.0}], 1.0),
    ([{"check": "[r for r in app.gp.mod_ranges() if r[1] == 13 and app.gp.graph.nodes[r[0]].get('modulator')]"},
      {"check": "any(dpg.get_item_type(i).endswith('DrawRect') for i in app.gp._readout_items)"},
      {"py": "(lambda r: (app.gp.graph.nodes[r]['params']['out_lo'], app.gp.graph.nodes[r]['params']['out_hi']))(next(r for r, b, i in app.gp.mod_ranges() if b == 13))"},
      {"graph_undo": True}, {"graph_undo": True}, {"graph_undo": True}, {"graph_undo": True}, {"graph_undo": True}], 0.8),
    ([{"check": "not [r for r in app.gp.mod_ranges() if r[1] == 13]"}, {"device": "127.0.0.1:8770"}, {"calibrate": True}], 5.0),
    ([{"check": "app.prefs.get('device_factor_measured', {}).get('fps') == 40.0"},
      {"py": "(app.prefs.pop('device_factor_measured', None), app.prefs.__setitem__('device_factor', 60.0))"}], 0.5),
    # every kind of face, live: the demo graph written into the project, built, and its glyphs asked after -
    # the Wave's dot moves, the Scope and the sparklines draw, the lights and meters are on the pins, the
    # Noise scrolls with its z, the Steps node lights its step, a hovered output shows its plot
    ([{"py": "__import__('runpy').run_path('tests/face_demo.py', run_name='x')['write'](app.project.path)[0]"},
      {"graph_open": "face_demo.json"}, {"graph_zoom": 1.0}, {"py": "app.gp.compile()"}], 22.0),
    ([{"check": "app.eng.names[app.eng.idx] == 'face_demo'"}, {"check": "app.gp._hist_n > 30"},
      {"check": "set(app.gp._live_glyphs.values()) >= {'wave', 'scope', 'spark', 'bars', 'strip', 'noise', 'steps'}"},
      {"check": "dpg.get_item_configuration('gglyph_3_dot')['center'][0] > 0"},
      {"check": "len(dpg.get_item_configuration('gglyph_4_line')['points']) > 20"},
      {"check": "len(dpg.get_item_configuration('gglyph_7_line')['points']) > 20"},
      {"check": "dpg.does_item_exist('gglyph_8') and dpg.does_item_exist('gglyph_9') and dpg.does_item_exist('gglyph_11') and dpg.does_item_exist('gglyph_15')"},
      {"check": "getattr(app.gp, '_noise_z', {}).get(20) is not None"},
      {"check": "app.gp._step_lit.get(5) is not None"},
      {"py": "len(app.gp._readout_items)"}, {"graph_hover": ["out", 3, "value"]}], 1.0),
    ([{"check": "app.gp._hover_out == (3, 'value')"}, {"check": "len(app.gp._readout_items) > 12"},
      {"check": "any(dpg.get_item_type(i).endswith('DrawCircle') for i in app.gp._readout_items)"}], 0.5),
    # a wire that closes a loop (the Multiply of the time back into its own b) gets a Delay; undone
    ([{"graph_open": "box_fire.json"}, {"py": "app.gp.on_link(None, (app.gp._pins[(11, 'out', 'result')], app.gp._pins[(11, 'in', 'b')]))"}], 1.0),
    ([{"expect": ["messages", "closed a loop"]}, {"py": "[n['type'] for n in app.gp.graph.nodes.values()].count('Delay')"}, {"graph_undo": True}], 0.5),
    # a Send / Receive pair added, named, and joined by the compiler (the pair is not in the C++)
    ([{"graph_open": "box_fire.json"}, {"py": "(app.gp.add_node('Send'), app.gp.add_node('Receive'))"},
      {"py": "app.gp.graph.link(6, 't', max(app.gp.graph.nodes) - 1, 'in')"},
      {"py": "'Receive' not in app.gp.graph.compile() and 'Send' not in app.gp.graph.compile()"}, {"graph_undo": True}, {"graph_undo": True}], 1.0),
    # MIDI learn without a controller: the window, Speed learnt from an injected CC and driven to 255, a typed pin
    # of the graph learnt and driven to the top of its range, the slider's right-click menu; the mappings cleared
    ([{"graph_open": "box_fire.json"}, {"action": "midi"}, {"midi_learn": {"kind": "fx", "key": "sx"}}, {"midi": [176, 7, 64]}], 1.0),
    ([{"expect": ["messages", "MIDI: CC 7 ch 1 -> "]}, {"expect": ["messages", "-> Speed"]}, {"midi": [176, 7, 127]}], 0.6),
    ([{"expect": ["inp_sx", "255"]},
      {"midi_learn": {"kind": "pin", "graph": "box_fire.json", "nid": 12, "name": "scale", "lo": 0.0, "hi": 12.0}}], 0.6),
    ([{"midi": [177, 8, 127]}], 0.6),
    ([{"expect": ["messages", "CC 8 ch 2 -> Noise #12 . scale"]}, {"py": "app.gp.graph.nodes[12]['inputs']['scale']"},
      {"py": "(num.set('inp_sx', 0), app.eng.fx.__setitem__('sx', 0))"}, {"midi": [176, 7, 100]}], 0.6),
    ([{"expect": ["inp_sx", "201"]}, {"py": "midi_ui.slider_menu(app, 'sx') or dpg.is_item_shown('midi_ctx')"}], 0.6),
    ([{"py": "dpg.hide_item('midi_ctx')"}, {"py": "dpg.hide_item('midi_win')"}, {"graph_undo": True},
      {"py": "(app.project.options.pop('midi', None), app.project.save())"}], 0.5),
    # the help: the guide in its window, a search that marks the words and scrolls to them, F1 with a node
    # selected landing on that node's entry, Back to where the guide was, the node's menu with its keys and
    # its reference row, the first-run panel; all put away again
    ([{"action": "guide"}], 1.0),
    ([{"check": "dpg.is_item_shown('reader_win') and reader_ui.S.doc == 'GUIDE.md'"}, {"check": "len(reader_ui.S.toc) >= 10"},
      {"py": "reader_ui.search(app, needle='snapshot')"}], 0.8),
    ([{"check": "reader_ui.S.hit is not None and dpg.does_item_exist(reader_ui.S.hit)"},
      {"check": "dpg.get_value('reader_found').startswith('1 of ')"}, {"check": "dpg.get_y_scroll('reader_body') > 100"},
      {"graph_open": "box_fire.json"}, {"graph_selected": [12]}, {"action": "node_help"}, {"graph_selected": []}], 1.5),
    ([{"check": "reader_ui.S.doc == 'NODES.md'"},
      {"check": "reader_ui.S.here == reader_ui.reader.heading_index(reader_ui.S.blocks, 'Noise')"},
      {"check": "reader_ui.S.history[-1][0] == 'GUIDE.md'"}, {"py": "reader_ui.back(app)"}], 1.0),
    ([{"check": "reader_ui.S.doc == 'GUIDE.md' and dpg.get_y_scroll('reader_body') > 100"},
      {"graph_ctx": ["node", 12, None, 400, 300]}], 0.6),
    ([{"check": "[dpg.get_item_configuration(i)['shortcut'] for i in dpg.get_item_children('graph_ctx', 1) "
                "if dpg.get_item_label(i) == 'mute (pass through)'] == [app.keys.label('mute')]"},
      {"check": "any(dpg.get_item_label(i) == 'Noise in the node reference...' for i in dpg.get_item_children('graph_ctx', 1))"},
      {"py": "dpg.configure_item('graph_ctx', show=False)"}, {"action": "welcome"}], 0.6),
    ([{"check": "dpg.is_item_shown('welcome_win')"}, {"py": "reader_ui.welcome_closed(app)"},
      {"check": "app.prefs.get('welcome_done') is True and not dpg.is_item_shown('welcome_win')"},
      {"py": "dpg.hide_item('reader_win')"}], 0.5),
    # the graph gets the room (canvas first): the graph most of the window, the 3-D view in its corner, the rail;
    # the panel opened at a section beside the rail, and folded; a Bitmap's properties over the canvas, closed;
    # the help at the pointer; the 3-D view tucked away and back, in another corner; the panes, and back
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}], 1.5),
    ([{"check": "room.active(app) and room.folded(app) and dpg.is_item_shown('rail_win') and dpg.is_item_shown('pip_win')"},
      {"check": "app._rects['main'][2] > 0.8 * dpg.get_viewport_client_width()"},
      {"check": "not dpg.is_item_shown('graph_help_box') and not dpg.is_item_shown('props_fly')"},
      {"check": "room.parent_is('cube_win', 'pip_win')"},
      {"py": "room.open_panel(app, 'parameters')"}], 1.0),
    ([{"check": "dpg.is_item_shown('side_win') and dpg.is_item_shown('rail_win') and not room.folded(app)"},
      {"py": "room.fold_panel(app)"}, {"graph_open": "smiley.json"}, {"graph_selected": [5]}], 1.5),
    ([{"check": "dpg.is_item_shown('props_fly') and room.parent_is('props_win', 'props_fly')"},
      {"py": "room.dismiss_props(app)"}], 0.6),
    ([{"check": "not dpg.is_item_shown('props_fly')"}, {"graph_selected": []}, {"py": "room.S.__setattr__('test_at', (600, 400))"},
      {"graph_hover": ["node", 5, None]}], 1.0),
    ([{"check": "dpg.is_item_shown('help_tip') and 'Bitmap' in dpg.get_value('help_tip_text')"},
      {"py": "room.S.__setattr__('test_at', None)"}, {"py": "room.set_tucked(app, True)"}], 1.0),
    ([{"check": "dpg.is_item_shown('pip_tab') and not dpg.is_item_shown('pip_win') and not app.cube_on()"},
      {"py": "(room.set_tucked(app, False), room.pip(app).__setitem__('corner', 'tl'), app.request_layout())"}], 1.0),
    ([{"check": "room.S.pip_rect[0] < app._rects['main'][0] + 40 and room.S.pip_rect[1] < app._rects['main'][1] + 80"},
      {"py": "(room.pip(app).__setitem__('corner', 'br'), room.set_on(app, False))"}], 1.5),
    ([{"check": "not room.active(app) and room.parent_is('cube_win', 'panes_row')"},
      {"check": "'cube' in app._rects and dpg.is_item_shown('graph_help_box') and not dpg.is_item_shown('rail_win')"},
      {"py": "room.set_on(app, True)"}, {"graph_open": "box_fire.json"}, {"key": "Home"}], 1.5),
    # Home puts the whole graph inside the canvas (the editor reports no position of its own: measured from its pane)
    ([{"check": "min(dpg.get_item_state(f'gnode_{n}')['rect_min'][0] for n in app.gp.graph.nodes "
                "if 'rect_min' in dpg.get_item_state(f'gnode_{n}')) >= app.gp.editor_origin()[0]"},
      {"check": "min(dpg.get_item_state(f'gnode_{n}')['rect_min'][1] for n in app.gp.graph.nodes "
                "if 'rect_min' in dpg.get_item_state(f'gnode_{n}')) >= app.gp.editor_origin()[1]"}], 0.5),
    # what has nothing to act on is greyed (the toolbar, the menus, a frame's buttons) and a key for it says why;
    # the confirm's answers weighed; the Send frame with no device offers one; a theme switch recolours the dialogs' lines
    ([{"graph_open": "box_fire.json"}, {"graph_selected": []}], 0.6),
    ([{"check": "not dpg.get_item_configuration(app._tb_btn['delete'])['enabled'] and not dpg.get_item_configuration('mi_delete')['enabled']"},
      {"check": "dpg.get_item_configuration(app._tb_btn['delete'])['tint_color'][3] < 0.5"},
      {"action": "delete"}, {"graph_selected": [12, 13]}], 0.6),
    ([{"expect": ["messages", "select a node first"]},
      {"check": "dpg.get_item_configuration(app._tb_btn['delete'])['enabled'] and dpg.get_item_configuration('mi_fold')['enabled']"},
      {"graph_selected": []},
      {"py": "chrome.confirm(app, 'Test', 'a question', [('Send', lambda: None, 'danger'), ('Cancel', None)])"}], 0.5),
    ([{"check": "[weight.kind_of(b) for b in dpg.get_item_children('confirm_buttons', 1)] == ['danger', 'quiet']"},
      {"py": "dpg.hide_item('confirm_dialog')"},
      {"py": "(setattr(app, '_dev_keep', app.project.options.get('device', '')), app.project.options.__setitem__('device', ''))"},
      {"frame": "send"}, {"py": "device_ui.refresh_send(app)"}], 1.0),
    ([{"check": "dpg.is_item_shown('send_find') and not dpg.get_item_configuration('send_script_btn')['enabled']"},
      {"py": "(app.project.options.__setitem__('device', app._dev_keep), device_ui.refresh_send(app))"}, {"frame_close": "send"},
      {"appearance": {"light": True}}], 1.5),
    ([{"check": "abs(dpg.get_item_configuration('confirm_text')['color'][0] * 255 - chrome.TEXT[0]) < 2"},
      {"appearance": {"light": False}}], 1.0),
    # a node's type changed with its wires kept; two nodes merged through an Add
    ([{"graph_open": "box_fire.json"}, {"py": "app.gp.change_type(3, 'Subtract') if app.gp.graph.nodes[3]['type'] == 'Multiply' else app.gp.change_type(3, 'Multiply')"}], 1.0),
    ([{"expect": ["messages", "is now"]}, {"graph_selected": [1, 2]}, {"py": "app.gp.merge_selected('Add')"}, {"graph_selected": []}], 1.0),
    ([{"expect": ["messages", "merged through Add"]}, {"graph_undo": True}, {"graph_undo": True}], 0.5),
    # two nodes folded into a sub-graph, entered, and back by the breadcrumb
    ([{"graph_open": "box_fire.json"}, {"graph_selected": [1, 2]}, {"py": "app.gp.make_sub_from_selection('smoke_sub')"},
      {"py": "app.gp.enter_sub(next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'sub:smoke_sub'))"}], 2.0),
    ([{"expect": ["messages", "sub-graph smoke_sub"]}, {"py": "dpg.is_item_shown('graph_crumbs')"}, {"py": "app.gp.back(1)"}], 1.0),
    ([{"expect": ["messages", "box_fire.json"]},
      {"py": "app.gp.unfold_sub(next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'sub:smoke_sub'))"}], 1.0),
    ([{"expect": ["messages", "unfolded"]}, {"graph_undo": True}, {"graph_undo": True}], 0.5),
    ([{"graph_selected": [1, 2]}, {"action": "align_left"}, {"action": "arrange"}, {"graph_undo": True}, {"graph_undo": True}], 1.0),
    ([{"graph_hover": ["out", 1, "value"]}, {"graph_hover": ["node", 9, ""]}], 0.6),
    ([{"gp_call": ["set_focus_mode", [True]]}, {"gp_call": ["set_focus_mode", [False]]}, {"graph_selected": []}], 0.6),
    ([{"script_preview": True}], 3.0),
    ([{"layout": "edit"}, {"open": "box_fire.cpp"}, {"ed_goto": 30}, {"ed_type": "// smoke"}, {"ed_key": ["Return", False, False]},
      {"find": "gc_sat"}, {"action": "find_next"}, {"action": "undo"}, {"action": "undo"}], 1.5),
    # find and replace, whole: the place and count, replace one, match case and whole word; the API reference inserts
    ([{"find": "SEGMENT"}, {"check": "app.code_ed.find_place()[1] > 2 and app.code_ed.find_place()[0] == 1"}, {"action": "find_next"},
      {"check": "app.code_ed.find_place()[0] == 2"}, {"action": "find_prev"}, {"check": "app.code_ed.find_place()[0] == 1"},
      {"py": "dpg.set_value('find_case', True) or dpg.set_value('find_text', 'sEGMENT') or app.find(False)"},
      {"check": "app.code_ed.find_place()[1] == 0"}, {"py": "dpg.set_value('find_case', False) or app.find(False)"},
      {"check": "app.code_ed.find_place()[1] > 2"},
      {"py": "dpg.set_value('find_word', True) or dpg.set_value('find_text', 'SEGMEN') or app.find(False)"},
      {"check": "app.code_ed.find_place()[1] == 0"}, {"py": "dpg.set_value('find_word', False) or dpg.set_value('find_text', 'gc_sat') or app.find(False)"},
      {"py": "(app.code_ed.find_place(), dpg.set_value('replace_text', 'gc_satX'), app.replace_one())"},
      {"check": "'gc_satX' in dpg.get_value('code') and dpg.get_value('code').count('gc_satX') == 1"},
      {"py": "app.api_pick('gc_sat(x)', 'test')"}, {"expect": ["edit_status", "inserted at the cursor"]},
      {"check": "'gc_sat(x)' in dpg.get_value('code')"},
      {"action": "undo"}, {"action": "undo"}, {"action": "undo"}], 1.5),
    ([{"layout": "both"}, {"geometry": {"kind": "matrix", "params": {"w": 32, "h": 16}}}, {"seg": "add"},
      {"seg": {"k": 1, "x0": 8, "y0": 4, "x1": 24, "y1": 12, "opacity": 160, "blend": 10}}, {"seg": "remove"},
      {"seg": "undo"}, {"py": "app.eng.seg_count()"}, {"expect": ["messages", "segments: undo"]}, {"seg": "remove"}], 1.5),
    ([{"geometry": {"kind": "cube", "params": {"B": 16}}}, {"compare": "Rainbow"}], 2.0),
    ([{"compare": ""}, {"sweep": ["sx", 3, False, False]}], 3.5),
    ([{"sweep": None}, {"key": "Q"}, {"key": "Q"}, {"key": "E"}, {"key": "E"}, {"key": "W"}, {"key": "W"}], 1.5),
    ([{"chrome": "shortcuts"}, {"chrome": "frames"}, {"chrome": "flash"}, {"feature": ["imu", False]}, {"feature": ["audio", "none"]},
      {"feature": ["imu", True]}, {"feature": ["audio", "pcm"]}, {"chrome": "usermods"}, {"usermod": ["add", "Temperature"]},
      {"usermod": ["off", "Temperature"]}, {"usermod": ["remove", "Temperature"]}, {"chrome": "about"}], 1.0),
    ([{"appearance": {"light": True}}, {"appearance": {"light": False}}], 1.0),
    ([{"gpu": False}, {"gpu": True}, {"gpu_net": False}, {"gpu_net": True}], 1.5),
    ([{"ui": False}, {"ui": True}, {"layout": "graph"}, {"measure": True}, {"randomise": True}], 1.0),
    ([{"layout": "both"}, {"arrangement": [["main", "cube"], ["side"]]}, {"pane_move": ["cube", "side", "top"]},
      {"pane_move": ["side", "main", "left"]}, {"pane_move": ["cube", "main", "centre"]}, {"layout": "graph"},
      {"layout": "edit"}, {"arrangement": [["main"], ["cube"], ["side"]]}], 2.5),
    # the Device frames: floating, docked by the button and by a grip drop, floated again
    ([{"layout": "graph"}, {"frame": "devices"}, {"frame": "send"}, {"frame": "flash"}, {"dock": ["devices", True]},
      {"pane_move": ["send", "cube", "bottom"]}, {"pane_move": ["flash", "side", "top"]}, {"pane_move": ["devices", "main", "right"]},
      {"dock": ["devices", False]}, {"dock": ["send", False]}, {"dock": ["flash", False]},
      {"arrangement": [["main"], ["cube", "props"], ["side"]]}], 3.0),
    # the shape editor: parts added, one placed by a click on the 3-D view, the grid layout, undo, and back to the cube
    ([{"layout": "both"}, {"frame": "shape"}, {"shape": ["clear"]}, {"shape": ["add", "ring"]}, {"shape": ["add", "panel"]},
      {"shape": ["add", "cube"]}, {"shape": ["select", 1]}, {"shape": ["place", 120, 120]}, {"shape": ["layout", "grid"]},
      {"shape": ["layout", "strip"]}, {"shape": ["undo"]},
      {"shape": ["mark", [0, 1]]}, {"shape": ["align", 2]}, {"shape": ["match", "scale"]}, {"shape": ["mark", []]}, {"shape": ["undo"]}, {"shape": ["undo"]},
      {"shape": ["segments"]}, {"seg": "remove"}, {"seg": "remove"},
      {"shape": ["preview", "parts", 1]}, {"shape": ["xmodel", "projects/default/export/_smoke.xmodel"]},
      {"dock": ["shape", True]}, {"dock": ["shape", False]},
      {"geometry": {"kind": "cube", "params": {"B": 16}}}], 4.0),
    # live output to the fake device on this machine, and the wiring test
    ([{"frame": "send"}, {"stream": "127.0.0.1"}, {"wiring_test": "chase"}, {"wiring_test": "index"}, {"wiring_test": "part"},
      {"wiring_test": "output"}, {"wiring_test": "white"}, {"wiring_test": "off"}], 4.0),
    ([{"stream": False}], 1.0),
    # every send to a device, against the fake WLED: the script, the settings, the shape, the ledmap
    ([{"frame": "devices"}, {"device": "127.0.0.1:8770"}, {"scan": "all"}], 6.0),
    ([{"layout": "graph"}, {"graph_open": "fan.json"}, {"py": "app.send_script()"}], 6.0),
    ([{"expect": ["send_status", "the device is running it"]}, {"effect": "Rainbow"}, {"py": "app.push_settings()"}], 3.0),
    ([{"expect": ["edit_status", "Rainbow"]}, {"py": "app.send_shape(True)"}, {"py": "app.send_ledmap(True)"}], 4.0),
    ([{"expect": ["edit_status", "ledmap"]}], 0.5),
    # a sequence: two steps from the sim, played, a step loaded back, one deleted
    ([{"frame": "sequence"}, {"effect": "Rainbow"}, {"seq": ["add"]}, {"effect": "Ace 3-D Maelstrom"}, {"seq": ["add"]},
      {"seq": ["field", "dur", 1.0]}, {"seq": ["play"]}], 3.0),
    # the sequence and the schedule sent to the fake: presets, the playlist, the timers with their Off preset
    ([{"seq": ["stop"]}, {"seq": ["load", 0]}, {"seq": ["ramp", "sx", 250]}, {"seq": ["ramp", "ix", 40, "up and back"]},
      {"check": "__import__('native.sequence', fromlist=['x']).ramp_of(app.project.options['sequence']['steps'][0], 'ix') == (40, 'up and back')"},
      {"seq": ["ramp_del", "ix"]}, {"check": "'ix' not in (app.project.options['sequence']['steps'][0].get('ramps') or {})"},
      {"seq": ["ramp", "ix", 40, "ease out"]},
      {"py": "__import__('native.sequence_ui', fromlist=['x']).send(app, run=True)"}], 22.0),
    ([{"expect": ["seq_log", "saved on the device"]}, {"seq": ["timer", "playlist"]}, {"seq": ["timer", "off"]},
      {"py": "__import__('native.sequence_ui', fromlist=['x']).send_timers(app)"}], 6.0),
    ([{"expect": ["seq_tlog", "timer(s) sent"]}, {"py": "__import__('native.sequence_ui', fromlist=['x']).read_timers(app)"}], 3.0),
    ([{"expect": ["seq_tlog", "read from the device"]}, {"seq": ["del", 1]}, {"seq": ["del", 0]}, {"seq": ["timer_del", 1]}, {"seq": ["timer_del", 0]},
      {"seq": ["tap"]}, {"seq": ["snap", 120.0, 4]}, {"camera": "front"}, {"camera": ["save", 1]}, {"camera": "isometric"}], 1.5),
    # undo in the frames: a deleted step comes back, and goes again on redo
    ([{"py": "len(app.project.options['sequence']['steps'])"}, {"seq": ["undo"]}, {"py": "len(app.project.options['sequence']['steps'])"},
      {"seq": ["redo"]}, {"py": "len(app.project.options['sequence']['steps'])"}, {"expect": ["messages", "sequence: redo"]}], 1.0),
    # custom palettes: one made, a stop added, used by the sim, one from the sim's palette, both removed
    ([{"frame": "palettes"}, {"cpal": ["new"]}, {"cpal": ["stop", 64, 0, 0, 255]}, {"cpal": ["use"]}, {"cpal": ["current"]},
      {"py": "__import__('native.palette_ui', fromlist=['x']).send(app, True)"}], 3.0),
    ([{"expect": ["pal_log", "palette(s) sent"]}, {"py": "__import__('native.palette_ui', fromlist=['x']).remove_there(app)"},
      {"cpal": ["del"]}, {"cpal": ["del"]}, {"cpal": ["undo"]}, {"py": "len(app.project.options.get('palettes') or [])"},
      {"expect": ["messages", "palettes: undo"]}, {"cpal": ["del"]}], 2.0),
    # LED outputs and power: the wiring split three ways, the limiter previewed and off again, the device's read and sent
    ([{"frame": "outputs"}, {"outputs": ["split", "one"]}, {"outputs": ["split", "count"]}, {"outputs": ["limit", 850]},
      {"outputs": ["abl", True]}, {"outputs": ["abl", False]}, {"outputs": ["limit", 0]},
      {"py": "__import__('native.outputs_ui', fromlist=['x']).read_device(app)"}], 3.0),
    ([{"expect": ["out_log", "output(s) read"]}, {"py": "__import__('native.outputs_ui', fromlist=['x']).send(app)"}], 3.0),
    ([{"expect": ["out_log", "sent"]}], 0.5),
    # the audio input: the device's read, a line-in preset sent (the reboot offered), the meter read
    ([{"frame": "audioin"}, {"audioin": ["read"]}], 2.0),
    ([{"expect": ["ain_log", "audio input read"]}, {"audioin": ["preset", "pcm1808"]}, {"audioin": ["pins", [13, 15, 14, 4]]},
      {"audioin": ["send"]}], 3.0),
    ([{"expect": ["ain_log", "after a reboot"]}, {"py": "dpg.hide_item('confirm_dialog')"}, {"audioin": ["meter", True]}], 2.5),
    ([{"expect": ["ain_source", "I2S digital"]}, {"audioin": ["meter", False]}, {"audioin": ["preset", "inmp441"]}], 1.0),
    # sad paths: a wire between types that do not convert, a graph with no output, a C++ effect that does not
    # compile, a device that is off - a status line each, never a traceback
    ([{"layout": "graph"}, {"py": "app.gp.new('sad_smoke')"},
      {"py": "app.gp.graph.links.append((next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Speed'), 'value', "
             "next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Output'), 'color'))"}, {"py": "app.gp.compile()"}], 3.0),
    ([{"expect": ["messages", "cannot take a float"]},
      {"py": "[app.gp._delete_node(i) for i, n in list(app.gp.graph.nodes.items()) if n['type'] == 'Output']"}, {"py": "app.gp.compile()"}], 3.0),
    ([{"expect": ["messages", "exactly one Output"]}, {"graph_open": "box_fire.json"}, {"py": "app.gp.compile(False)"},
      {"layout": "edit"}, {"open": "box_fire.cpp"}, {"ed_goto": 30},
      {"ed_type": "this is not C++ ;"}, {"ed_key": ["Return", False, False]}, {"py": "app.edit_build()"}], 12.0),
    ([{"expect": ["edit_status", "problem"]}, {"action": "undo"}, {"action": "undo"}, {"layout": "graph"}, {"graph_open": "fan.json"},
      {"device": "127.0.0.1:1"}, {"py": "app.send_script()"}], 8.0),
    ([{"expect": ["messages", "failed"]}, {"device": "127.0.0.1:8770"}], 1.0),
    # the messages (C10): the graph that did not compile held as a problem, counted in the footer; the log lists it;
    # go to from another layout opens the graph pane with the interface (it went to a full frame once)
    ([{"check": "'graph:sad_smoke.json' in messages.HELD and dpg.is_item_shown('msg_problems')"},
      {"py": "messages.show_log(app)"}, {"check": "dpg.is_item_shown('log_win')"}, {"py": "dpg.hide_item('log_win')"},
      {"layout": "both"}, {"py": "messages.goto(app, messages.HELD['graph:sad_smoke.json'])"}], 1.0),
    ([{"check": "app.ui and app.layout == 'graph' and app.gp.file == 'sad_smoke.json'"},
      {"graph_open": "box_fire.json"}, {"py": "setattr(app, '_goto_nid', next(i for i, n in app.gp.graph.nodes.items() if n['type'] == 'Output'))"},
      {"graph_open": "fan.json"}, {"layout": "both"},
      {"py": "messages.goto(app, {'node': ('box_fire.json', app._goto_nid, False)})"}], 1.0),
    ([{"check": "app.ui and app.layout == 'graph' and app.gp.file == 'box_fire.json' and app.gp.ext_sel == [app._goto_nid]"},
      {"py": "messages.clear(app, 'graph:sad_smoke.json')"}], 0.5),
    # a problem report bundled, the project zipped (both land in captures/; the test removes them)
    ([{"report": True}, {"py": "app.export_project_zip()"}, {"expect": ["edit_status", "project zipped"]}], 3.0),
    # the library: thumbnails made for the graphs, the frame docked and floated
    ([{"frame": "library"}, {"dock": ["library", True]}, {"dock": ["library", False]}], 5.0),
    ([{"graph_open": "gyro_sand.json"}, {"graph_export": None}, {"confirm": 0}, {"feature": ["imu", False]},
      {"graph_import": "projects/default/export/gyro_sand.graph.json"}, {"confirm": 0}, {"export_usermod": True}], 3.0),
    ([{"layout": "both"}, {"popout": ["cube", True]}, {"layout": "graph"}], 5.0),
    ([{"popout": ["net", True]}, {"layout": "both"}], 4.0),
    ([{"popout": ["cube", False]}, {"popout": ["net", False]}], 2.0),
    ([{"section": ["geometry", False]}, {"section": ["audio", "effect", "above"]}, {"section": ["parameters", "live", "below"]},
      {"section": ["geometry", True]}, {"section": "reset"}], 1.5),
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"action": "select_all"}, {"action": "frame_selected"},
      {"graph_select": [3]}, {"action": "select_up"}, {"action": "select_down"}, {"action": "select_invert"}, {"action": "select_none"},
      {"graph_select": [4]}, {"action": "swap_inputs"}, {"action": "frame_sel"}, {"action": "snap"}, {"action": "snap"},
      {"gp_call": ["set_label", [4, "my node"]]}, {"action": "dissolve"}, {"action": "undo_history"}, {"action": "repeat"},
      {"palette": "sel"}, {"key": "Escape"}, {"graph_zoom": 0.2}, {"action": "frame_all"}, {"graph_zoom": 1.0}, {"graph_undo": True}, {"graph_undo": True}, {"graph_undo": True}, {"graph_undo": True}], 3.0),
]



def send(cmds, wait):
    json.dump(cmds, open(CMD, "w"))
    time.sleep(wait)


def main():
    os.makedirs(os.path.dirname(CMD), exist_ok=True)
    project = os.path.join(ROOT, "projects", "default", "project.json")
    saved = open(project, encoding="utf-8").read() if os.path.exists(project) else None
    graph = os.path.join(ROOT, "projects", "default", "graphs", "box_fire.json")
    saved_graph = open(graph, encoding="utf-8").read() if os.path.exists(graph) else None
    gdir = os.path.join(ROOT, "projects", "default", "graphs")
    sdir = os.path.join(ROOT, "projects", "default", "subgraphs")
    subs_before = set(os.listdir(sdir)) if os.path.isdir(sdir) else set()
    caps_before = set(os.listdir(os.path.join(ROOT, "captures"))) if os.path.isdir(os.path.join(ROOT, "captures")) else set()
    before = set(os.listdir(gdir)) if os.path.isdir(gdir) else set()      # a first run makes the project
    STUDIO_FILE = os.path.join(ROOT, "projects", "studio.json")   # the prefs: a saved view would otherwise stay
    saved_prefs = open(STUDIO_FILE, encoding="utf-8").read() if os.path.exists(STUDIO_FILE) else None
    from fake_wled import FakeWled                          # the device every send goes to, and the DDP receiver
    ddp = FakeWled(port=8770, ddp_port=4048).start()
    with open(LOG, "w") as log:
        # the console variant of the packaged app keeps its stdout, which is the log the test reads
        cmd = [EXE] if EXE else [sys.executable, "-u", "-m", "native.app"]
        env = dict(os.environ, STUDIO_NO_UPDATE_CHECK="1", STUDIO_NO_WELCOME="1")
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        time.sleep(9 if not EXE else 30)                 # the packaged app unpacks itself first
        for cmds, wait in STEPS:
            if proc.poll() is not None:
                print("the app exited early"); break
            send(cmds, wait)
    finally:
        proc.kill()
        time.sleep(1)
        if saved is not None:
            open(project, "w", encoding="utf-8").write(saved)
        if saved_graph is not None:
            open(graph, "w", encoding="utf-8").write(saved_graph)
        if saved_prefs is not None:
            open(STUDIO_FILE, "w", encoding="utf-8").write(saved_prefs)
        for f in (set(os.listdir(gdir)) if os.path.isdir(gdir) else set()) - before:
            if before:                                                         # a project made by this run keeps its examples
                os.remove(os.path.join(gdir, f))                               # the import's copy
    text = open(LOG, encoding="utf-8", errors="replace").read()
    ddp.stop()
    print(f"ddp: {ddp.ddp_packets} packets, {ddp.ddp_frames} frames received from the stream; "
          f"the fake got {len(ddp.files)} file(s), {len(ddp.presets) - 1} preset(s), {len(ddp.cfg['timers']['ins'])} timer(s)")
    bad = [l for l in text.splitlines() if "Traceback" in l or "Error:" in l or "command file:" in l]
    if "remote control" not in text:
        bad.append("the app's output was not captured (no 'remote control' line): a buffered stdout, or the wrong exe")
    if ddp.ddp_frames < 10:
        bad.append(f"the DDP stream sent {ddp.ddp_frames} frames; 10 or more expected")
    bad += [l for l in text.splitlines() if "EXPECT FAILED" in l]
    rep = next((l.split(None, 1)[1].strip() for l in text.splitlines() if l.startswith("report ")), "")
    if not rep or not os.path.exists(rep):
        bad.append("Help > Report a problem made no zip")
    else:
        import zipfile
        names = zipfile.ZipFile(rep).namelist()
        for want in ("version.json", "doctor.txt", "machine.json", "project.json", "README.txt", "messages.txt"):
            if want not in names:
                bad.append(f"the report zip lacks {want}")
        os.remove(rep)
    for f in (set(os.listdir(sdir)) if os.path.isdir(sdir) else set()) - subs_before:
        os.remove(os.path.join(sdir, f))                        # the sub-graph the fold made
    for f in ("effects/face_demo.cpp", "graphs/face_demo.json"):    # the face demo's graph and its build
        if os.path.exists(os.path.join(ROOT, "projects", "default", f)):
            os.remove(os.path.join(ROOT, "projects", "default", f))
    for f in (set(os.listdir(os.path.join(ROOT, "captures"))) if os.path.isdir(os.path.join(ROOT, "captures")) else set()) - caps_before:
        if f.endswith(".zip"):                                  # the project zip the run made
            os.remove(os.path.join(ROOT, "captures", f))
    for name in ("/studio.bin", "/ledmap.json", "/geometry.bin"):
        if name not in ddp.files:
            bad.append(f"the fake device never received {name}")
    if bad:
        print("smoke: FAILED")
        i = text.find("Traceback")
        print(text[i - 200:i + 1500] if i >= 0 else "\n".join(bad[:20]))
        return 1
    print(f"smoke: ok ({len(STEPS)} steps, log {LOG})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
