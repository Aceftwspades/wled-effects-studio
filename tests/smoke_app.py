"""Drive the running app through its main flows and fail on any traceback.

The app takes commands from a JSON file (native/app.py service_command),
which is how every panel here was checked without a hand on the mouse.
This launches the app, walks the layouts, opens a graph and a code effect,
exercises the editor, segments, A/B, sweep, the script preview, the
dialogs and the keys, then reads the app's log for tracebacks.

It works in a project of its own (SMOKE), made from the examples at the
start and deleted at the end, so it starts the same on any machine and
leaves the others alone; the app's remote control is turned on for it
(STUDIO_REMOTE_CONTROL=1), in the private scratch folder (native/scratch.py).

    python tests/smoke_app.py          # from studio; ~60 s; exits 1 on a traceback

It is deliberately not a pytest: it needs the window, the engine and a
minute; run it before a release, not on every save.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))                  # the studio's own source: native.scratch, the films
from native import scratch                                 # noqa: E402 - the app's private scratch folder
# STUDIO_EXE: the packaged app's exe to test instead of the tree - its
# folder is then the home (projects/, build/) the test saves and restores
EXE = os.environ.get("STUDIO_EXE")
ROOT = os.path.dirname(os.path.abspath(EXE)) if EXE else os.path.dirname(HERE)
CMD = scratch.path("command.json")
LOG = scratch.path("smoke.log")
SMOKE = "smoke_run"                    # the run's own project, made from the examples and deleted after (issue #9)

# S18: two sides of a small tree filmed while the camera plan played - made by make_films() through ffmpeg
# (LEDs 5 and 17 hidden from the front, 30 from the side); without ffmpeg these steps are left out
MAP_FILMS = [scratch.path(f"map_side{a}.mp4") for a in (0, 90)]
_part = "app.project.geometry.params['parts'][0]"
_TREE = {"kind": "tree", "name": "tree", "params": {"strands": 9, "per_strand": 40, "height": 90.0, "base": 54.0, "top": 3.0,
         "turns": 0.0, "degrees": 360.0, "zigzag": True}, "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0, "reverse": False}
MAP_STEPS = [
    # the plan: the wiring test lights one LED at a time in the sim, the device's own frame has the plan's 60 LEDs
    ([{"geometry": {"kind": "cube", "params": {"B": 16}}}, {"py": "camera_map_ui.show(app)"}, {"py": "num.set('map_n', 60)"},
      {"py": "num.set('map_on', 0.2)"}, {"py": "camera_map_ui.play(app)"}], 3.0),
    ([{"check": "app.wiring is not None and app.wiring.mode in ('index', 'off', 'white') and len(app._map_frame) == 60 * 3"},
      {"check": "int((np.frombuffer(app._map_frame, np.uint8).reshape(-1, 3).max(1) > 0).sum()) in (0, 1, 60)"},
      {"expect": ["map_play_words", "left"]}, {"py": "camera_map_ui.stop(app)"}], 0.5),
    # two films read (the second waits its turn), their LEDs found; a side added and dropped
    ([{"check": "app.wiring is None and app._map_frame is None and app._map['play'] is None"},
      {"py": "camera_map_ui._add_side(app)"}, {"py": "camera_map_ui._add_side(app)"}, {"py": "camera_map_ui._drop_side(app, 2)"},
      {"py": "[camera_map_ui._state(app).__setitem__('film_for', k) or camera_map_ui._film_chosen(app, p) for k, p in enumerate("
             + repr(MAP_FILMS) + ")]"}], 8.0),
    ([{"check": "[s['angle'] for s in app._map['sides']] == ['0°', '90°'] and app._map['busy'] is None and not app._map['queue']"},
      {"check": "all(s['found'] and len(s['found']) >= 57 for s in app._map['sides'])"},
      {"check": "all(s['thumb'] and dpg.does_item_exist(s['thumb'][0]) for s in app._map['sides'])"},
      {"py": "num.set('map_height', 180.0)"}, {"py": "camera_map_ui.make(app)"}], 1.0),
    # the part: 60 LEDs in the shape, 180 cm tall at 60 a metre, those one side missed estimated and listed by the checks
    ([{"check": "app.project.geometry.kind == 'shape' and app.project.geometry.count == 60"},
      {"check": f"{_part}['name'].startswith('mapped lights') and {{5, 17, 30}} <= set({_part}['guessed']) and len({_part}['guessed']) <= 5"},
      {"check": f"abs(float(np.ptp(np.asarray({_part}['params']['points'])[:, 2])) - units.from_unit(180.0, {{'unit': 'cm'}})) < 0.01"},
      {"check": "any('no two sides' in c.text for c in shape_checks.run(app))"},
      {"expect": ["map_result", "60 LEDs"]},
      {"frame": "shape"}, {"py": "shape_ui.select(app, [0])"},
      {"py": "next(c for c in shape_checks.run(app) if 'no two sides' in c.text).show()"}], 0.8),
    # an estimate dragged where it is (by hand) is one no longer
    ([{"py": "setattr(app, '_shape_drag', (0, 5)) or setattr(app, '_shape_drag_to', [0.0, 0.0, 50.0]) or shape_ui.release(app)"},
      {"check": f"5 not in {_part}['guessed'] and 17 in {_part}['guessed']"},
      {"py": "chrome.close_dialog('map_win')"}, {"geometry": {"kind": "cube", "params": {"B": 16}}}], 0.8),
]

STEPS = [
    # the run's own project, from the examples; Maelstrom's graph compiled, built and put on the effects list
    # (a batch that starts with wait_build is taken once the build in hand is loaded, however long that is here)
    # Live (rebuild as the graph changes) off for the steps that build by hand - it is on by default; the
    # steps that are about it turn it on
    ([{"project": SMOKE}, {"graph_auto": False}], 3.0),
    ([{"wait_build": True}, {"check": f"app.project.path.endswith({SMOKE!r})"}, {"layout": "graph"},
      {"graph_open": "maelstrom.json"}, {"py": "app.gp.compile()"}, {"py": "app.project.set_imported('maelstrom.cpp', True)"}], 5.0),
    ([{"wait_build": True}, {"expect": ["edit_status", "loaded cubefx_"]}, {"layout": "both"}, {"effect": "Maelstrom"}], 1.5),
    # a rewire seen at once: with Live on, the edit runs as bytecode in the sim's Studio Script effect a moment
    # after it is made - under the graph's own name - while its C++ builds; the build takes over at the same clock
    ([{"check": "app.eng.names[app.eng.idx] == 'Maelstrom'"}, {"layout": "graph"}, {"graph_open": "maelstrom.json"},
      {"py": "app.eng.set_now(50000)"}, {"graph_auto": True}, {"graph_link": [4, "value", 23, "b"]}], 0.7),
    ([{"check": "app.gp.standin_on() and 'Studio Script' in app.eng.names[app.eng.idx]"},
      {"check": "dpg.get_value('fx_combo') == 'Maelstrom' and app.eng.clock()[0] >= 50000"},
      {"expect": ["messages", "runs it as a script until its build lands"]}], 0.3),
    ([{"wait_build": True}, {"check": "app.eng.names[app.eng.idx] == 'Maelstrom' and not app.gp.standin_on()"},
      {"check": "app.eng.clock()[0] >= 50000 and app.gp._shown is not None"},
      {"py": "setattr(app, '_lib_live', app.eng.library)"}, {"graph_zoom": 0.85}], 0.9),
    # an edit that changes no code (a zoom rebuilds the editor) builds nothing, Live or not
    ([{"check": "not app.building and app.eng.library == app._lib_live and not app.gp.standin_on()"},
      {"graph_zoom": 1.0}, {"graph_auto": False}, {"graph_undo": True}, {"layout": "both"}], 0.5),
    # a graph compiled and built: the toolchain works (the bundled one in a packaged run) and box_fire.cpp exists for the code steps
    ([{"check": "app.eng.names[app.eng.idx] == 'Maelstrom'"}, {"layout": "graph"}, {"graph_open": "box_fire.json"},
      {"py": "app.gp.compile()"}], 5.0),
    # a node with a wire OUT deleted, then undone: its wires go with it - one used to stay in the editor, tied to a
    # freed pin, and the undo's rebuild crashed the app (issue #4)
    ([{"wait_build": True}, {"expect": ["edit_status", "loaded cubefx_"]}, {"py": "setattr(app, '_links_before', len(app.gp.links))"},
      {"graph_select": [3]}, {"action": "delete"}], 0.5),
    ([{"check": "3 not in app.gp.graph.nodes and len(app.gp.links) == len(app.gp.graph.links) < app._links_before"},
      {"check": "len(dpg.get_item_children('node_editor', 0) or []) == len(app.gp.links)"}, {"graph_undo": True}], 0.5),
    ([{"check": "3 in app.gp.graph.nodes and len(app.gp.links) == app._links_before"}, {"action": "select_none"},
      {"key": "Home"}, {"speed": 0.5},
      # a typed value poked into the running effect's parameter table: no rebuild
      {"py": "(app.eng.names[app.eng.idx], (lambda k: app.gp.live_poke(k[0], k[1], 0.42))(next(iter(app.gp._live))))"}], 1.5),
    ([{"expect": ["stat_txt", "speed 1/2x"]}, {"action": "speed_up"}, {"action": "speed_up"}, {"action": "speed_up"}], 1.0),
    ([{"expect": ["stat_txt", "speed 4x"]}, {"action": "speed_reset"}, {"layout": "both"}], 0.8),
    # before and after (A/B): B keeps this build; a rebuild moves A on and leaves B on it, both on the same effect
    # with the same sliders; another effect for B puts it back on the current build
    ([{"compare_before": True}], 1.0),
    ([{"check": "app.ab is not None and app.ab_before and app.ab_name == app.eng.names[app.eng.idx] and app.ab.library != app.eng.library"},
      {"check": "'as built at' in dpg.get_value('cube_cap')"},
      {"py": "setattr(app, '_ab_libs', (app.ab.library, app.eng.library))"}, {"py": "app.gp.compile()"}], 5.0),
    ([{"wait_build": True}, {"check": "app.eng.library != app._ab_libs[1] and app.ab.library == app._ab_libs[0] and bool(app.ab_before)"},
      {"param": ["sx", 201]}], 0.8),
    ([{"check": "app.ab.names[app.ab.idx] == app.eng.names[app.eng.idx] and app.ab.fx['sx'] == app.eng.fx['sx'] == 201"},
      {"compare": "Rainbow"}], 1.0),
    ([{"check": "app.ab_before is None and app.ab_name == 'Rainbow' and app.ab.library.endswith('_ab' + __import__('os').path.splitext(app.eng.library)[1])"},
      {"compare": ""}], 0.5),
    ([{"check": "app.ab is None and app.ab_before is None"}], 0.2),
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
    # a node's wires lit (C11): the selected Noise's wires bright, a wire elsewhere faded; nothing selected, all as
    # they were; the minimap in the corner View > Minimap picks, and off the 3-D view's corner when that is its pick
    ([{"py": "setattr(app.gp, '_hover_cache', (__import__('time').time() + 5, None))"},   # the real pointer left out of it
      {"graph_selected": [12]}], 0.5),
    ([{"check": "app.gp.wire_state(12, 'x') == 'lit' and app.gp.wire_state(13, 'a') == 'lit'"},
      {"check": "any(app.gp.wire_state(b, i) == 'faded' for b, i in app.gp.links.values())"}, {"graph_selected": []}], 0.5),
    ([{"check": "all(app.gp.wire_state(b, i) == 'normal' for b, i in app.gp.links.values())"},
      {"py": "room.set_minimap(app, corner='tl')"}, {"check": "app.gp._mini_corner == 'tl' and dpg.get_value('menu_minimap_tl')"},
      {"py": "room.set_minimap(app, corner=room.pip(app)['corner'])"},
      {"check": "app.gp._mini_corner != room.pip(app)['corner'] or not room.pip_on(app)"},
      {"py": "room.set_minimap(app, corner='auto')"}], 0.5),
    # nodes spend their height on the work (C12): a control node's label in its title, its label and where it starts
    # in the properties (the title follows an edit there, and undo); a range's two settings on one row
    ([{"graph_selected": [1]}], 1.0),
    ([{"check": "dpg.get_item_configuration('gnode_1')['label'] == 'Speed: Rise'"},
      {"check": "(lambda ws: len(ws) == 2 and len({dpg.get_item_info(dpg.get_item_info(w)['parent'])['parent'] for w in ws}) == 1)"
                "([w for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) in ((9, 'in_lo'), (9, 'in_hi'))])"},
      {"py": "setattr(app, '_meta_w', next(w for g in dpg.get_item_children('graph_props', 1) for w in (dpg.get_item_children(g, 1) or []) "
             "if dpg.get_item_user_data(w) == (1, 'label')))"},
      {"check": "dpg.get_value(app._meta_w) == 'Rise'"}, {"py": "app.gp._on_param(app._meta_w, 'Rising')"},
      {"check": "dpg.get_item_configuration('gnode_1')['label'] == 'Speed: Rising'"}, {"graph_undo": True}], 0.8),
    ([{"check": "dpg.get_item_configuration('gnode_1')['label'] == 'Speed: Rise' and app.gp.graph.nodes[1]['params']['label'] == 'Rise'"},
      {"graph_selected": []}], 0.5),
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
    ([{"py": f"__import__('runpy').run_path({os.path.join(HERE, 'face_demo.py')!r}, run_name='x')['write'](app.project.path)[0]"},   # the tree's: a packaged app has no tests/
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
      {"py": "app.gp.set_selection([2])"}, {"action": "frame_selected"}, {"py": "app.gp.set_zoom(1.0, app.gp.editor_origin())"},
      {"action": "select_none"}], 1.0),
    # a bool output's light, the Audio node's beat: framed in the top left first - in the whole graph at macOS's
    # 1280 x 646 it sat under the minimap, where no readout is drawn
    ([{"check": "any(dpg.get_item_type(i).endswith('DrawCircle') for i in app.gp._readout_items)"}], 0.5),
    # every node in the library on one graph (tests/node_gallery.py, the tree's): what is drawn in a node lies
    # within the width it is laid out to - a title, a field, a face - a name too long is cut with "...", an
    # output's name ends at its pin and an input's row starts at its - at 100%, 70% and 140%
    ([{"py": f"setattr(app, '_gal', __import__('runpy').run_path({os.path.join(HERE, 'node_gallery.py')!r}, run_name='x'))"},
      {"py": "app._gal['write'](app.project.path)[0]"}, {"layout": "graph"}, {"graph_open": "node_gallery.json"},
      {"graph_zoom": 1.0}], 2.5),
    ([{"py": "app._gal['check'](app)"}, {"check": "not app._gal['check'](app)"}, {"graph_zoom": 0.7}], 2.0),
    ([{"py": "app._gal['check'](app)"}, {"check": "not app._gal['check'](app)"}, {"graph_zoom": 1.4}], 2.0),
    ([{"py": "app._gal['check'](app)"}, {"check": "not app._gal['check'](app)"}, {"graph_zoom": 1.0}], 0.5),
    # an unwired coordinate reads the pixel: a Noise dropped in says "position x" on its field and compiles per
    # pixel; a number typed makes it a number again, a reset brings the words back; a vector pin (Voronoi's) is
    # a button that gives it a typed value
    ([{"py": "app.gp.new('implicit_smoke')"}, {"py": "setattr(app, '_nz', app.gp.graph.add('Noise', (460, 380)))"},
      {"py": "setattr(app, '_vz', app.gp.graph.add('Voronoi', (460, 620)))"}, {"py": "app.gp.rebuild()"}, {"graph_zoom": 1.0}], 0.6),
    ([{"check": "dpg.get_item_configuration(f'gin_{app._nz}_x_w')['format'] == 'position x'"},
      {"check": "'(X3)' in app.gp.graph.compile() and dpg.get_item_type(f'gin_{app._vz}_pos_w').endswith('Button')"},
      {"py": "app.gp._on_input(f'gin_{app._nz}_x_w', 0.25)"}], 0.4),
    ([{"check": "'%' in dpg.get_item_configuration(f'gin_{app._nz}_x_w')['format'] and app.gp.graph.nodes[app._nz]['inputs'].get('x') == 0.25"},
      {"py": "app.gp._reset_input(app._nz, 'x', None)"},
      {"py": "app.gp._implicit_to_typed(None, None, (app._vz, 'pos'))"}], 0.6),
    ([{"check": "dpg.get_item_configuration(f'gin_{app._nz}_x_w')['format'] == 'position x'"},
      {"check": "not dpg.get_item_type(f'gin_{app._vz}_pos_w').endswith('Button') and 'pos' in app.gp.graph.nodes[app._vz]['inputs']"}], 0.2),
    # Math's second pin only for the operations that read it - sqrt has one input - and kept while a wire is on it;
    # its operations grouped in the dropdown, a group's name picked changing nothing
    ([{"graph_open": "box_fire.json"}, {"py": "setattr(app, '_mz', app.gp.graph.add('Math', (60, 900)))"}, {"py": "app.gp.rebuild()"}], 0.5),
    ([{"check": "dpg.does_item_exist(f'gin_{app._mz}_b') and '-- compare --' in dpg.get_item_configuration(next(w for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (app._mz, 'op')))['items']"},
      {"py": "dpg.get_item_callback(next(w for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (app._mz, 'op')))(next(w for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (app._mz, 'op')), 'sqrt')"}], 0.5),
    ([{"check": "not dpg.does_item_exist(f'gin_{app._mz}_b') and app.gp.graph.nodes[app._mz]['params']['op'] == 'sqrt'"},
      {"py": "dpg.get_item_callback(next(w for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (app._mz, 'op')))(next(w for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (app._mz, 'op')), '-- compare --')"}], 0.3),
    ([{"check": "app.gp.graph.nodes[app._mz]['params']['op'] == 'sqrt' and dpg.get_value(next(w for w in app.gp._widgets if dpg.does_item_exist(w) and dpg.get_item_user_data(w) == (app._mz, 'op'))) == 'sqrt'"},
      {"py": "(app.gp.graph.link(13, 'result', app._mz, 'b'), app.gp.rebuild())"}], 0.4),
    ([{"check": "dpg.does_item_exist(f'gin_{app._mz}_b')"}, {"py": "(app.gp.graph.remove(app._mz), app.gp.rebuild())"}], 0.3),
    # what each node costs: a profiling build of the graph run in an engine of its own - each node then says its
    # share of the frame and its time on the device, the status the frame's; compiled again, they are old
    ([{"graph_open": "box_fire.json"}, {"graph_zoom": 1.0}, {"py": "app.gp.measure_costs()"}], 25.0),
    ([{"check": "app.gp._costs and app.gp._costs['frame_ms'] > 0 and not app.building"},
      {"check": "abs(sum(s for s, ms in app.gp._costs['nodes'].values()) + app.gp._costs['rest'] - 1.0) < 1e-6"},
      {"check": "len(app.gp._cost_items) > 0"}, {"expect": ["messages", "on the device"]},
      {"py": "app.gp.compile(False)"}], 0.5),
    ([{"check": "app.gp._costs is None and not app.gp._cost_items"}], 0.3),
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
    # a MIDI clock on the port: started, it takes the synth's beat (a beat at its first tick); stopped, the synth's
    # own again - its tempo put back after (the ticks came faster than any tempo: the slider's top)
    ([{"py": "app.syn.__setattr__('kick_req', False)"}, {"midi": [0xFA]}, {"midi": [0xF8]}, {"midi": [0xF8]},
      {"midi": [0xF8]}, {"midi": [0xF8]}], 0.2),
    ([{"midi": [0xF8]}, {"check": "app.syn.external and app.syn.bpm in (120, 200)"},       # within the half second a clock may pause
      {"expect": ["messages", "MIDI clock: the synth's beat follows it"]}, {"midi": [0xFC]}], 0.4),
    ([{"check": "not app.syn.external"}, {"expect": ["messages", "the synth keeps its own beat again"]},
      {"py": "(setattr(app.syn, 'bpm', 120), num.set('inp_bpm', 120))"}], 0.3),
    # OSC beside MIDI: on a port (any free one), a fader learnt as a knob is - its 0..1 finer than MIDI's 128 steps -
    # then a real datagram to that port, sent from inside the app, moves the slider; off again
    ([{"py": "midi_ui._st(app)['osc'].__setitem__('host', '127.0.0.1')"},
      {"py": "midi_ui.set_osc(app, on=True, port=0)"}, {"midi_learn": {"kind": "fx", "key": "ix"}},
      {"osc": ["/1/fader1", 0.5]}], 0.6),
    ([{"expect": ["messages", "MIDI: OSC /1/fader1 -> "]}, {"check": "app.eng.fx['ix'] == 128 and app.osc.port > 0"},
      {"expect": ["osc_state", "listening on"]},
      {"py": "__import__('socket').socket(2, 2).sendto(__import__('native.osc', fromlist=['osc']).message('/1/fader1', 0.2), "
             "('127.0.0.1', app.osc.port))"}], 0.8),
    ([{"check": "app.eng.fx['ix'] == 51"}, {"py": "midi_ui.set_osc(app, on=False)"}], 0.3),
    ([{"check": "app.osc.port is None and dpg.get_value('osc_state') == ''"},
      {"py": "dpg.hide_item('midi_ctx')"}, {"py": "dpg.hide_item('midi_win')"}, {"graph_undo": True},
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
    ([{"layout": "graph"}, {"graph_open": "box_fire.json"}, {"py": "room.fold_panel(app)"}], 1.5),    # folded, whatever the prefs say
    ([{"check": "room.active(app) and room.folded(app) and dpg.is_item_shown('rail_win') and dpg.is_item_shown('pip_win')"},
      {"check": "app._rects['main'][2] > 0.8 * dpg.get_viewport_client_width()"},
      {"check": "not dpg.is_item_shown('graph_help_box') and not dpg.is_item_shown('props_fly')"},
      {"check": "room.parent_is('cube_win', 'pip_win')"},
      {"py": "room.open_panel(app, 'parameters')"}], 1.0),
    ([{"check": "dpg.is_item_shown('side_win') and dpg.is_item_shown('rail_win') and not room.folded(app)"},
      {"py": "room.fold_panel(app)"}, {"graph_open": "question_block.json"}, {"graph_selected": [29]}], 1.5),   # 29: a Bitmap
    ([{"check": "dpg.is_item_shown('props_fly') and room.parent_is('props_win', 'props_fly')"},
      {"py": "room.dismiss_props(app)"}], 0.6),
    ([{"check": "not dpg.is_item_shown('props_fly')"}, {"graph_selected": []}, {"py": "room.S.__setattr__('test_at', (600, 400))"},
      {"graph_hover": ["node", 29, None]}], 1.0),
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
    # any node with something to set brings its properties up (12, a Noise: its settings and its free input); a value
    # set there is the node's field's too, and one set on the node theirs; undone, both go back; a node with nothing
    # to set (6, a Time) brings none
    ([{"graph_selected": [12]}], 1.0),
    ([{"check": "dpg.is_item_shown('props_fly') and {dpg.get_item_user_data(w) for w in app.gp._props_widgets} >= "
                "{(12, 'octaves'), (12, 'roughness'), (12, 'scale')}"},
      {"py": "setattr(app, '_twins', lambda name: [dpg.get_value(w) for w in app.gp._widgets if dpg.does_item_exist(w) "
             "and dpg.get_item_user_data(w) == (12, name)])"},
      {"py": "(lambda w: (dpg.set_value(w, 4.5), app.gp._on_input(w, 4.5)))"
             "(next(w for w in app.gp._props_widgets if dpg.get_item_user_data(w) == (12, 'scale')))"},
      {"check": "app.gp.graph.nodes[12]['inputs']['scale'] == 4.5 and app._twins('scale') == [4.5, 4.5]"},
      {"py": "(lambda w: (dpg.set_value(w, 0.25), app.gp._on_param(w, 0.25)))"
             "(next(w for w in app.gp._widgets if w not in app.gp._props_widgets and dpg.does_item_exist(w) "
             "and dpg.get_item_user_data(w) == (12, 'roughness')))"},
      {"check": "app.gp.graph.nodes[12]['params']['roughness'] == 0.25 and app._twins('roughness') == [0.25, 0.25]"},
      {"graph_undo": True}, {"graph_undo": True}], 1.0),
    ([{"check": "app.gp.graph.nodes[12]['inputs']['scale'] != 4.5 and 4.5 not in app._twins('scale')"},
      {"check": "app.gp.graph.nodes[12]['params']['roughness'] != 0.25 and 0.25 not in app._twins('roughness')"},
      {"graph_selected": [6]}], 1.0),
    ([{"check": "not dpg.is_item_shown('props_fly')"}, {"graph_selected": []}], 0.5),
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
    ([{"graph_hover": ["out", "auto", "value"]}, {"graph_hover": ["node", 9, ""]}], 0.6),
    # the 3-D view in the graph's corner: the frame of the pane last clicked in round it, not at the screen's corner;
    # its placed controls' words read from their tooltips; maximize lays it over the canvas, the same button puts it back
    ([{"py": "setattr(app, 'focus', 'cube_win')"}, {"py": "room.set_max(app, False)"}], 0.6),
    ([{"check": "not room.pip_on(app) or tuple(app._screen_rect('cube_win')[:2]) == tuple(room.S.pip_rect[:2])"},
      {"check": "{'pip_max', 'pip_size', 'pip_tuck', 'grip_cube_win', 'appearance_win_x'} <= chrome.PLACED"},
      {"check": "'over the whole graph' in chrome.placed_words('pip_max') and 'another pane' in chrome.placed_words('grip_cube_win')"},
      {"py": "room.set_max(app, True)"}], 0.8),
    ([{"check": "not room.pip_on(app) or (room.S.pip_rect[2] > 600 and not dpg.is_item_shown('pip_size') and 'back to its corner' in chrome.placed_words('pip_max'))"},
      {"py": "room.set_max(app, False)"}], 0.6),
    ([{"check": "not room.pip_on(app) or (room.S.pip_rect[2] < 600 and dpg.is_item_shown('pip_size'))"}], 0.2),
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
    # each segment its own colours: the panel shows the current one's, an edit lands on it alone, kept with the
    # project's segments
    ([{"py": "app.on_color(0, (255, 0, 0))"}, {"seg": "add"}, {"py": "app.on_color(0, (0, 0, 255))"}, {"seg": 0}], 0.8),
    ([{"check": "app.seg_cols[0] == 0xFF0000 and app.eng.segments()[1]['colors'][0] == 0x0000FF"},
      {"check": "app.project.options['segments'][1]['colors'][0] == 0x0000FF"}, {"seg": 1}], 0.5),
    ([{"check": "app.seg_cols[0] == 0x0000FF and app.eng.segments()[0]['colors'][0] == 0xFF0000"}, {"seg": "remove"}], 0.5),
    ([{"geometry": {"kind": "cube", "params": {"B": 16}}}, {"compare": "Rainbow"}], 2.0),
    ([{"compare": ""}, {"sweep": ["sx", 3, False, False]}], 3.5),
    ([{"sweep": None}, {"key": "Q"}, {"key": "Q"}, {"key": "E"}, {"key": "E"}, {"key": "W"}, {"key": "W"}], 1.5),
    # a plain key from the panel changes nothing and says where it works (C13); presentation shows how to leave
    # it, and Esc does
    ([{"py": "setattr(app, '_lay_before', (app.layout, app.ui))"}, {"key": "Q", "over": "panel"},
      {"check": "(app.layout, app.ui) == app._lay_before"}, {"expect": ["messages", "works with the pointer over"]},
      {"action": "presentation"}], 0.6),
    ([{"check": "not app.ui and app._present_hint is not None and dpg.does_item_exist('present_hint')"},
      {"check": "len(dpg.get_item_children('present_hint', 2) or []) >= 2"}, {"key": "Escape"}], 0.5),
    ([{"check": "app.ui and app._present_hint is None"}], 0.3),
    # the menus (C14): Window opens a frame and closes it, its check following; the palette runs a menu command
    # that is no action; a node's menu leads with what can be done and ends with its reference; the add menu
    # starts at its search
    ([{"py": "chrome.toggle_window(app, 'library')"}], 1.0),
    ([{"check": "chrome.window_open(app, 'library') and dpg.get_value('menu_win_library')"},
      {"py": "chrome.toggle_window(app, 'library')"}], 0.8),
    ([{"check": "not chrome.window_open(app, 'library') and not dpg.get_value('menu_win_library')"},
      {"check": "any(p.endswith('Message log...') for p, _ in chrome.menu_commands(app))"},
      {"check": "not any('mi_' in (dpg.get_item_alias(k) or '') for _, k in chrome.menu_commands(app))"},
      {"palette_run": "message log"}], 0.6),
    ([{"check": "dpg.is_item_shown('log_win')"}, {"py": "dpg.hide_item('log_win')"}, {"layout": "graph"},
      {"graph_open": "box_fire.json"}, {"py": "setattr(app.gp, '_ctx', ('node', 12, None))"}, {"py": "app.gp._fill_ctx_menu()"}], 0.8),
    ([{"check": "(lambda ks: [dpg.get_item_type(k).split('::')[-1] for k in ks].index('mvMenuItem') <= 4)(dpg.get_item_children('graph_ctx', 1))"},
      {"check": "'node reference' in dpg.get_item_configuration([k for k in dpg.get_item_children('graph_ctx', 1) "
                "if dpg.get_item_type(k).endswith('mvMenuItem')][-1])['label']"},
      {"check": "dpg.get_item_alias(dpg.get_item_children('graph_menu_list', 1)[0]) == 'graph_search'"},     # the list leads with its search
      {"check": "dpg.get_item_parent('graph_desc') == dpg.get_item_parent('graph_menu_list')"},          # the description beside it
      {"py": "dpg.configure_item('graph_ctx', show=False)"}], 0.5),
    # the toolbar (C15): the frames in words in a wide window, icons in a narrow one; an open frame lit
    ([{"py": "setattr(app, '_vp0', (dpg.get_viewport_width(), dpg.get_viewport_height()))"}, {"viewport": [1900, 1000]}], 1.2),
    ([{"check": "dpg.is_item_shown('tb_frames_words') and not dpg.is_item_shown('tb_frames_icons')"},
      {"viewport": [1000, 760]}], 1.2),
    ([{"check": "dpg.is_item_shown('tb_frames_icons') and not dpg.is_item_shown('tb_frames_words')"},
      {"py": "chrome.toggle_window(app, 'library')"}], 1.0),
    ([{"check": "dpg.get_item_theme('tb_frw_library') == chrome._word_theme(chrome.ACCENT)"},
      {"py": "chrome.toggle_window(app, 'library')"}, {"py": "(dpg.set_viewport_width(app._vp0[0]), dpg.set_viewport_height(app._vp0[1]))"}], 1.0),
    # the views (C16): unlit LEDs black until View > Unlit LEDs as dim dots (their default off), the floor on; each
    # turned over by its action and back; the GPU point cloud draws its dots while they are on
    ([{"layout": "both"}, {"py": "[app.prefs.pop(k, None) for k in ('unlit_dots', 'view_floor')] and None"}], 0.5),
    ([{"check": "not app.view_option('unlit_dots') and app.view_option('view_floor') and app.view_extras() == (None, True)"},
      {"action": "unlit_dots"}, {"action": "view_floor"}], 0.8),
    ([{"check": "app.view_extras()[0] is not None and not app.view_extras()[1] and dpg.get_value('menu_unlit_dots') and not dpg.get_value('menu_view_floor')"},
      {"check": "app.point_quads is None or app.point_quads.dots"}, {"action": "unlit_dots"}, {"action": "view_floor"}], 0.8),
    ([{"check": "app.view_extras() == (None, True) and not dpg.get_value('menu_unlit_dots')"},
      {"check": "app.point_quads is None or (not app.point_quads.dots and app.point_quads.floor)"}], 0.3),
    # the frames (C17): the gradient turning unless another look is picked (the default with nothing kept); kept
    ([{"py": "app.prefs.pop('frame_style', None)"}, {"check": "chrome.frame_style(app) == 'turning' == chrome.FRAME_STYLE_DEFAULT"},
      {"frame_style": "outline"}], 0.4),
    ([{"check": "app.frames.style == 'outline' and app.prefs.get('frame_style') == 'outline'"}, {"frame_style": "turning"}], 0.4),
    ([{"check": "app.frames.style == 'turning' and dpg.get_value('frames_style') == 'The gradient, turning'"}], 0.3),
    # Appearance in tabs (the Selection frames window one of them): each opens with all of it in view
    ([{"py": "chrome.show_appearance(app, 'colours')"}], 0.8),
    ([{"check": "not dpg.does_item_exist('frames_win') and dpg.get_value('app_tabs') in ('app_tab_colours', dpg.get_alias_id('app_tab_colours'))"},
      {"check": "dpg.is_item_visible('app_cat_colours') and dpg.is_item_visible('app_col_accent')"},
      {"py": "chrome.show_frames(app)"}], 0.8),
    ([{"check": "dpg.get_value('app_tabs') in ('app_tab_frames', dpg.get_alias_id('app_tab_frames'))"},
      # or, on a screen too short for it (macOS's runner: 1280 x 646), the dialog as tall as the window, scrolling;
      # when neither, the geometry says why
      {"check": "(dpg.is_item_visible('gc_status') and dpg.is_item_visible('frames_style')) or "
                "(dpg.is_item_visible('frames_style') and "
                "dpg.get_item_rect_size('appearance_win')[1] >= dpg.get_viewport_client_height() - 12) or "
                "f\"view {dpg.get_viewport_client_width()}x{dpg.get_viewport_client_height()} "
                "win {dpg.get_item_pos('appearance_win')} {dpg.get_item_rect_size('appearance_win')} "
                "status {dpg.get_item_rect_min('gc_status')} {dpg.is_item_visible('frames_style')}\""},
      {"py": "chrome.show_appearance(app, 'size')"}], 0.8),
    ([{"check": "dpg.is_item_visible('app_ui_scale')"}, {"py": "chrome.show_appearance(app, 'view')"},
      {"py": "chrome.set_look(app, preset='cinematic')"}], 0.8),
    # the 3-D view's look (look.py): Cinematic picked - its fields follow, the live view's layers drawn, a picture
    # made with it; a value moved is kept over the preset; the studio look again
    ([{"check": "dpg.get_value('look_preset') == 'Cinematic' and abs(dpg.get_value('look_spill') - 0.5) < 1e-6"},
      {"check": "app.cube_quads is None or (dpg.get_item_configuration(app.cube_quads.layers.over_items[0])['show'] "
                "and dpg.get_item_configuration(app.cube_quads.layers.under_item)['show'])"},
      {"check": "app.view_image(app.net_image(), 160).shape == (160, 160, 3)"},
      # the floor a mirror: the reflection's quads drawn under the cube while the camera is above the floor
      {"check": "app.cube_quads is None or app.eye_above_floor() is False or "
                "any(dpg.get_item_configuration(q)['show'] for qs in app.cube_quads.mirror.values() for q in qs)"},
      {"py": "chrome.set_look(app, key='grain', value=0.9)"}], 0.5),
    ([{"check": "app.view_look()['grain'] == 0.9 and dpg.get_value('look_preset') == 'Cinematic, grain changed'"},
      {"py": "chrome.set_look(app, preset='studio')"}], 0.5),
    ([{"check": "not __import__('native.look', fromlist=['x']).active(app.view_look())"},
      {"check": "app.cube_quads is None or not dpg.get_item_configuration(app.cube_quads.layers.over_items[0])['show']"},
      {"check": "app.cube_quads is None or not any(dpg.get_item_configuration(q)['show'] for qs in app.cube_quads.mirror.values() for q in qs)"},
      # every shape in parity: a sphere's LEDs as glowing sprites with their reflection
      {"geometry": {"kind": "sphere", "params": {"w": 24, "h": 12}}}, {"py": "chrome.set_look(app, preset='night')"}], 1.5),
    ([{"check": "app.point_quads is not None and app.point_quads.sprite and app.point_quads.reflect > 0"},
      {"check": "any(dpg.get_item_configuration(q)['show'] for q in app.point_quads.mirror_items)"},
      {"check": "app.view_image(app.net_image(), 160).shape == (160, 160, 3)"},
      {"py": "chrome.set_look(app, preset='studio')"}, {"geometry": {"kind": "cube", "params": {"B": 16}}}], 1.5),
    ([{"check": "app.cube_quads is not None"},
      {"py": "chrome.close_dialog('appearance_win')"}], 0.4),
    # the footer (C18): power and the device's fps; the stats popover live while open, above its button; Esc closes it
    ([{"check": "'device ~' in dpg.get_value('stat_txt') and 'brightness' not in dpg.get_value('stat_txt')"},
      {"py": "chrome.toggle_stats(app)"}], 0.8),
    ([{"check": "dpg.is_item_shown('stats_pop') and dpg.get_value('stat_mean') != '-' and 'ms a frame' in dpg.get_value('stat_app')"},
      {"check": "dpg.get_item_pos('stats_pop')[1] + dpg.get_item_rect_size('stats_pop')[1] <= dpg.get_item_rect_min('stat_more')[1]"},
      {"key": "Escape"}], 0.4),
    ([{"check": "not dpg.is_item_shown('stats_pop')"}], 0.2),
    ([{"chrome": "shortcuts"}, {"chrome": "frames"}, {"chrome": "flash"}, {"feature": ["imu", False]}, {"feature": ["audio", "none"]},
      {"feature": ["imu", True]}, {"feature": ["audio", "pcm"]}, {"chrome": "usermods"}, {"usermod": ["add", "Temperature"]},
      {"usermod": ["off", "Temperature"]}, {"usermod": ["remove", "Temperature"]}, {"chrome": "about"}], 1.0),
    # the Flash frame's firmware sources: a .bin of the fake device's chip (an S3) chosen, asked about, flashed
    # to it through /update and recorded; WLED's releases (a list given here, not the network) matched to its
    # chip; a built-in cube effect left out of the studio's build; and back to the studio's build
    ([{"frame": "flash"}, {"device": "127.0.0.1:8770"},
      {"py": "open(app.project.path + '/export/smoke_s3.bin', 'wb').write(bytes([0xE9, 3, 0, 0, 0, 4, 8, 0x40, 0, 0, 0, 0, 9, 0]) + bytes(4082)) and None"},
      {"py": "device_ui._set_source(app, 'file')"}, {"py": "device_ui._pick_bin(app, app.project.path + '/export/smoke_s3.bin')"}], 0.8),
    ([{"check": "dpg.is_item_shown('flash_file_row') and not dpg.is_item_shown('flash_fx') and not dpg.is_item_shown('flash_env_row')"},
      {"check": "any('an esp32-s3 image' in dpg.get_value(i) for i in dpg.get_item_children('flash_manifest', 1))"},
      {"py": "device_ui.start_flash(app)"}], 0.6),
    ([{"check": "dpg.is_item_shown('confirm_dialog') and 'cube effects' in dpg.get_value('confirm_text')"},
      {"py": "dpg.hide_item('confirm_dialog')"}, {"py": "device_ui.start_flash(app, confirmed=True)"}], 14.0),
    ([{"check": "app.flash_job.done and app.flash_job.ok and app.flash_job.source == 'file'"},
      {"check": "app.project.options['flash_history'][-1]['firmware'] == 'smoke_s3.bin'"},
      {"py": "setattr(app, '_fw_rels', [{'tag': 'v16.0.1', 'name': 'x', 'pre': False, 'date': '2026-09-20', 'assets': ["
             "{'name': n, 'url': '', 'size': 1000} for n in ('WLED_16.0.1_ESP32.bin', 'WLED_16.0.1_ESP32-S3_8MB_opi.bin', "
             "'WLED_16.0.1_ESP32-S3_4M_qspi.bin')]}])"},
      {"py": "setattr(app, '_fw_fetching', True)"}, {"py": "device_ui._set_source(app, 'release')"},
      {"py": "(setattr(app, '_fw_fetching', False), setattr(app, '_fw_fresh', True))"}], 0.8),
    ([{"check": "dpg.is_item_shown('flash_rel_row') and dpg.get_item_configuration('flash_asset')['items'] == "
                "['WLED_16.0.1_ESP32-S3_4M_qspi.bin', 'WLED_16.0.1_ESP32-S3_8MB_opi.bin']"},
      {"check": "any('several flash sizes' in dpg.get_value(i) for i in dpg.get_item_children('flash_manifest', 1))"},
      {"py": "device_ui._set_source(app, 'studio')"},
      # the cube_fx sources come from a WLED checkout: CI and a packaged app without one have no catalog
      {"py": "flash.builtin_catalog() and device_ui._builtin_toggle(app, flash.builtin_catalog()[0]['file'], False)"}], 0.8),
    ([{"check": "not flash.builtin_catalog() or (dpg.is_item_shown('flash_fx') and flash.builtin_chosen(app.project) == [e['file'] for e in flash.builtin_catalog()][1:])"},
      {"check": "not flash.builtin_catalog() or any('built-in cube effects: %d of %d' % (len(flash.builtin_catalog()) - 1, len(flash.builtin_catalog())) in dpg.get_value(i) "
                "for i in dpg.get_item_children('flash_manifest', 1))"},
      {"py": "device_ui._ship_all(app, True)"}], 0.5),
    ([{"check": "app.project.options.get('builtin_ship') is None"}, {"py": "chrome.close_all_frames(app)"}], 0.3),
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
      {"shape": ["preview", "parts", 1]}, {"shape": ["xmodel", f"projects/{SMOKE}/export/_smoke.xmodel"]},
      {"dock": ["shape", True]}, {"dock": ["shape", False]}], 4.0),
    # building in 3-D (the ninth pass, S1-S3): each part its colour, the selected one bright; the part under the
    # pointer (the hooks' stand-in for it); the view's own keys - a view along an axis is orthographic, 5 turns it
    # over, F frames the selected part, Home everything; a pan; the view's frame held while a part moves, grown when
    # one is added out of it
    ([{"py": "chrome.close_all_frames(app) or [dpg.hide_item(w) for w in ('usermods_win', 'keys_win', 'about_win', 'appearance_win') "
             "if dpg.does_item_exist(w)] and None"},                    # the dialogs and frames the steps above left over the view
      {"layout": "cube", "with_ui": True}, {"frame": "shape"}, {"dock": ["shape", True]}, {"shape": ["clear"]},
      {"shape": ["layout", "strip"]}, {"shape": ["add", "ring"]}, {"shape": ["add", "strip"]}, {"shape": ["select", 1]}], 1.5),
    ([{"check": "view3d.editing(app)"},
      {"check": "(lambda out: tuple(out[30]) == tuple(shape_view.part_colour(1)) and "
                "np.abs(out[0].astype(int) - shape_view.part_colour(0) * shape_view.DIM_OTHERS).max() <= 1)"
                "(shape_view.colours(app, app.frame_rgb(app.eng).reshape(-1, 3)))"},
      {"led_at": [30, "hover"]}], 0.6),
    ([{"check": "app._shape_hover is not None and app._shape_hover[1] == 1 and abs(app._shape_hover[0] - 30) <= 2 or "
                "str((app._shape_hover, app._test_pointer, shape_view.covers(app), [dpg.get_item_alias(w) for w in dpg.get_windows() if dpg.is_item_shown(w)]))"},
      {"led_at": [0, "leave"]}, {"key": "1", "over": "view"}], 0.6),
    ([{"check": "app.ortho and abs(abs(app.yaw) - np.pi) < 1e-3 and abs(app.pitch) < 1e-3"}, {"key": "5", "over": "view"}], 0.3),
    ([{"check": "not app.ortho"}, {"key": "7", "over": "view"}, {"py": "setattr(app, '_d0', app.dist)"}, {"key": "F", "over": "view"}], 0.6),
    ([{"check": "app.ortho and app.pitch > 1.5 and app.dist < app._d0"},
      {"py": "view3d.pan(app, 80, 30)"}, {"key": "Home", "over": "view"}], 0.6),
    ([{"check": "np.linalg.norm(app.look) < 1e-6 and abs(app.dist - view3d.HOME[2]) < 1e-6"},
      {"py": "setattr(app, '_f0', view3d.frame(app))"}, {"shape": ["nudge", {"pos": [60.0, 0.0, 0.0]}]}], 0.6),
    ([{"check": "np.allclose(view3d.frame(app)[0], app._f0[0]) and view3d.frame(app)[1] == app._f0[1]"},
      {"shape": ["add", "panel"]}], 0.6),
    ([{"check": "view3d.frame(app)[1] > app._f0[1]"}, {"check": "shape_view.mode(app) == 'parts'"},
      {"py": "shape_view.set_mode(app, 'effect')"}], 0.3),
    ([{"check": "shape_view.colours(app, app.frame_rgb(app.eng).reshape(-1, 3)) is not None and app.prefs.get('shape_colours') == 'effect'"},
      {"py": "shape_view.set_mode(app, 'parts')"}, {"key": "0", "over": "view"}], 1.0),
    # S4-S7 through the tools' test hook (the pointer's stand-in): an arrow dragged is one undo step; a click picks the
    # ring, Shift-click adds the panel, a click on nothing clears, a Shift-box takes all three; G X 10 Enter moves the strip
    # six LEDs (10 cm at 60 a metre), R Z 90 turns it, S 2 scales it, G Y 5 Esc puts it back; G to the ring's end joins it
    # after the ring; the ring's menu locks it (a click passes over it), hidden it is dark; a copy made and deleted; a ring
    # handle turns the strip
    ([{"shape": ["select", 1]}, {"py": "setattr(app, '_shape_place', False)"},                 # placing by hand (above) hides the handles
      {"py": "setattr(app, '_x0', app.project.geometry.params['parts'][1]['pos'][0]) or setattr(app, '_u0', len(app._shape_undo))"},
      {"tool": ["press", {"handle": ["axis", 0]}]}, {"tool": ["drag", {"from_press": [40, 0]}]}, {"tool": ["drag", {"from_press": [80, 0]}]},
      {"tool": ["release", {"from_press": [80, 0]}]}], 0.6),
    ([{"check": "app.project.geometry.params['parts'][1]['pos'][0] != app._x0 and len(app._shape_undo) == app._u0 + 1"},
      {"tool": ["press", {"part": 0}]}, {"tool": ["release", {"part": 0}]}], 0.4),
    ([{"check": "shape_ui.selection(app) == {0}"}, {"tool": ["press", {"part": 2}, ["shift"]]}, {"tool": ["release", {"part": 2}, ["shift"]]}], 0.4),
    ([{"check": "shape_ui.selection(app) == {0, 2}"}, {"tool": ["press", {"view": [0.01, 0.02]}]}, {"tool": ["release", {"view": [0.01, 0.02]}]}], 0.4),
    ([{"check": "shape_ui.selection(app) == set()"}, {"tool": ["press", {"view": [0.01, 0.02]}, ["shift"]]},
      {"tool": ["drag", {"view": [0.99, 0.98]}, ["shift"]]}, {"tool": ["release", {"view": [0.99, 0.98]}, ["shift"]]}], 0.4),
    ([{"check": "shape_ui.selection(app) == {0, 1, 2}"}, {"shape": ["select", 1]}, {"tool": ["hover", {"led": 40}]},
      {"py": "setattr(app, '_x0', app.project.geometry.params['parts'][1]['pos'][0])"},
      {"key": "G", "over": "view"}, {"key": "X"}, {"key": "1"}, {"key": "0"}, {"key": "Return"}], 0.5),
    ([{"check": "abs(app.project.geometry.params['parts'][1]['pos'][0] - app._x0 - 6.0) < 1e-6"},
      {"py": "setattr(app, '_rz0', app.project.geometry.params['parts'][1]['rot'][2])"},
      {"key": "R", "over": "view"}, {"key": "Z"}, {"key": "9"}, {"key": "0"}, {"key": "Return"}], 0.5),
    ([{"check": "(lambda r: abs((r[2] - app._rz0 - 90.0 + 180.0) % 360.0 - 180.0) < 1e-3 or str((r, app._rz0)))(app.project.geometry.params['parts'][1]['rot'])"},
      {"key": "S", "over": "view"}, {"key": "2"}, {"key": "Return"}], 0.5),
    ([{"check": "abs(float(app.project.geometry.params['parts'][1]['scale']) - 2.0) < 1e-6"},
      {"py": "setattr(app, '_p0', list(app.project.geometry.params['parts'][1]['pos']))"},
      {"key": "G", "over": "view"}, {"key": "Y"}, {"key": "5"}, {"key": "Escape"}], 0.5),
    ([{"check": "app.project.geometry.params['parts'][1]['pos'] == app._p0 and app._tool is None"}, {"shape": ["undo"]}], 0.5),
    ([{"check": "float(app.project.geometry.params['parts'][1]['scale']) == 1.0"},
      {"key": "G", "over": "view"}, {"tool": ["hover", {"join": [1, 0]}]}], 0.6),
    ([{"check": "app._tool and app._tool.get('join') and app._tool['join'][0] == 'after' and app._tool['join'][1] == 0"},
      {"key": "Return"}], 0.5),
    ([{"expect": ["messages", "joined after ring 1"]}, {"tool": ["right", {"led": 5}]}], 0.5),
    ([{"check": "dpg.is_item_shown('shape_ctx') and shape_ui.selection(app) == {0}"},
      {"py": "dpg.hide_item('shape_ctx') or next(r for r in shape_tools.menu_rows(app, 0) if r and r[0] == 'Lock')[2]()"}], 0.5),
    ([{"check": "app.project.geometry.params['parts'][0].get('locked')"}, {"shape": ["select", 2]},
      {"tool": ["press", {"led": 5}]}, {"tool": ["release", {"led": 5}]}], 0.4),
    ([{"check": "shape_ui.selection(app) == set()"}, {"py": "shape_ui.set_part(app, 0, locked=False, hidden=True)"}], 0.4),
    ([{"check": "(lambda out: int(out[5].max()) == 0)(shape_view.colours(app, app.frame_rgb(app.eng).reshape(-1, 3)))"},
      {"py": "shape_ui.set_part(app, 0, hidden=False)"}, {"shape": ["select", 2]}, {"action": "shape_dup"}], 0.5),
    ([{"check": "len(app.project.geometry.params['parts']) == 4 and app._tool and app._tool['kind'] == 'modal'"},
      {"key": "Escape"}, {"action": "shape_delete"}], 0.5),
    ([{"check": "len(app.project.geometry.params['parts']) == 3 and app._tool is None"},
      {"py": "shape_tools.set_mode(app, 'turn')"}, {"shape": ["select", 1]},
      {"py": "setattr(app, '_r0', list(app.project.geometry.params['parts'][1]['rot']))"},
      {"tool": ["press", {"handle": ["ring", 2]}]}, {"tool": ["drag", {"from_press": [0, 70]}]}, {"tool": ["release", {"from_press": [0, 70]}]}], 0.6),
    ([{"check": "(lambda r: r != app._r0 or str((r, app._r0)))(app.project.geometry.params['parts'][1]['rot'])"},
      {"py": "shape_tools.set_mode(app, 'move')"}, {"py": "shape_ui.select(app, [])"},
      {"py": "shape_ui.set_shape_option(app, density=30.0)"}], 0.5),
    # S8-S13: the shape's density (what is shown); a length typed in the unit sets the count; the gallery joins a strip
    # on from the selected one's end and puts a tree after it; a run drawn from above (three corners, Enter); a corner
    # moved in the table; copies round the origin and a mirror, live, made separate; undo and redo
    ([{"check": "units.density(app.project.geometry.params) == 30.0 and 'the shape' in dpg.get_value('shape_part_kind')"},
      {"py": "shape_ui.set_shape_option(app, density=60.0, unit='cm')"}, {"shape": ["select", 1]},
      {"py": "shape_ui._set_field(app, 1, shape_fields.FIELDS['strip'][1], 100.0)"}], 0.6),
    ([{"check": "app.project.geometry.params['parts'][1]['params']['n'] == 60"},
      {"py": "shape_gallery.show(app, 'strip')"}, {"py": "shape_gallery.add(app, app._gallery_part)"}], 0.8),
    ([{"check": "len(app.project.geometry.params['parts']) == 4 and not dpg.is_item_shown('shape_gallery')"},
      {"check": "(lambda P: float(np.linalg.norm(shapes.ends(P[2])[0] - (shapes.ends(P[1])[2] + shapes.ends(P[1])[3] * shapes.ends(P[1])[4]))) < 1e-3)"
                "(app.project.geometry.params['parts'])"},
      {"py": "shape_gallery.choose(app, 'tree')"}, {"py": "shape_gallery.add(app, app._gallery_part)"}], 0.8),
    ([{"check": "[q['kind'] for q in app.project.geometry.params['parts']] == ['ring', 'strip', 'strip', 'tree', 'panel']"},
      {"key": "7", "over": "view"}, {"key": "Home", "over": "view"}, {"py": "shape_run.start(app)"}], 0.8),
    ([{"tool": ["press", {"view": [0.3, 0.8]}]}, {"tool": ["release", {"view": [0.3, 0.8]}]},
      {"tool": ["press", {"view": [0.5, 0.8]}]}, {"tool": ["release", {"view": [0.5, 0.8]}]},
      {"tool": ["press", {"view": [0.5, 0.6]}]}, {"tool": ["release", {"view": [0.5, 0.6]}]}], 0.5),
    ([{"check": "shape_run.active(app) and len(app._run['corners']) == 3"}, {"key": "Return"}], 0.6),
    ([{"check": "(lambda q: q['kind'] == 'polyline' and len(q['params']['points']) == 3)(app.project.geometry.params['parts'][shape_ui._sel(app)])"},
      {"check": "not shape_run.active(app)"},
      {"py": "shape_run._set_corner(app, shape_ui._sel(app), 2, [0.0, 0.0, 0.0])"}], 0.5),
    ([{"check": "np.allclose(shape_run.world_corners(app.project.geometry.params['parts'][shape_ui._sel(app)])[2], 0.0, atol=1e-3)"},
      {"py": "shape_ui.set_copies(app, shape_ui._sel(app), n=3, turn=120.0, axis='z', about='origin')"}], 0.5),
    ([{"check": "shapes.copies(app.project.geometry.params['parts'][shape_ui._sel(app)]) == 3"},
      {"py": "shape_ui.set_mirror(app, shape_ui._sel(app), x=True)"}], 0.5),
    ([{"check": "shapes.copies(app.project.geometry.params['parts'][shape_ui._sel(app)]) == 6"},
      {"py": "setattr(app, '_n0', app.project.geometry.count) or shape_ui.make_separate(app, shape_ui._sel(app))"}], 0.5),
    ([{"check": "app.project.geometry.count == app._n0 and len(shape_ui.selection(app)) == 4"}, {"shape": ["undo"]}], 0.5),
    ([{"check": "shapes.copies(app.project.geometry.params['parts'][shape_ui._sel(app)]) == 6"}, {"py": "shape_ui.redo(app)"}], 0.5),
    ([{"check": "len(app.project.geometry.params['parts']) == 9 and app.project.geometry.count == app._n0"},
      {"py": "shape_ui.set_group(app, [0, 1], 'walls')"}], 0.5),
    ([{"check": "[q.get('group') for q in app.project.geometry.params['parts'][:3]] == ['walls', 'walls', None]"},
      {"check": "any(dpg.get_item_configuration(i).get('label', '').strip() == 'walls' for i in dpg.get_item_children('shape_parts', 1) "
                "for i in (dpg.get_item_children(i, 1) or []))"},
      {"key": "0", "over": "view"}, {"py": "shape_ui.select(app, [3]) or shape_tools.duplicate(app)"}, {"key": "Escape"}], 0.8),
    # S16: a copy left on top of its part is found (and "show me" frames it); S17: GEOMETRY > shape from a cube changes
    # nothing but opens the start; an object from it (the matrix) is the first part - and the geometry becomes the shape
    ([{"check": "any('sit on another' in c.text for c in shape_checks.run(app))"},
      {"py": "next(c for c in shape_checks.run(app) if 'sit on another' in c.text).show()"},
      {"geometry": {"kind": "cube", "params": {"B": 16}}}], 0.8),
    ([{"py": "app.on_geom_kind(None, 'shape')"}], 0.8),
    ([{"check": "app.project.geometry.kind == 'cube' and dpg.get_value('geom_kind') == 'cube' and dpg.does_item_exist('start_obj_0')"},
      {"py": "shape_start.choose(app, 0)"}, {"py": "shape_gallery.add(app, app._gallery_part)"}], 1.0),
    ([{"check": "app.project.geometry.kind == 'shape' and app.project.geometry.count == 256 and dpg.get_value('geom_kind') == 'shape'"},
      {"dock": ["shape", False]}, {"geometry": {"kind": "cube", "params": {"B": 16}}}], 1.0),
    *MAP_STEPS,
    # S19: a matrix-only effect on a shape's one-row layout says so under the effect (not on the cube); a grid that leaves
    # LEDs dark behind others is a check; the tree tutorial opens at its chapter
    ([{"geometry": {"kind": "shape", "params": {"parts": [_TREE]}}}, {"effect": "Ace 3-D Plasma"}], 1.0),
    ([{"check": "dpg.is_item_shown('fx_fit_note') and 'matrix' in dpg.get_value('fx_fit_note')"},
      {"geometry": {"kind": "shape", "params": {"parts": [_TREE], "layout": "grid"}}}], 1.0),
    ([{"check": "app.project.geometry.collisions > 0 and any('grid layout puts' in c.text for c in shape_checks.run(app))"},
      {"geometry": {"kind": "cube", "params": {"B": 16}}}], 1.0),
    ([{"check": "not dpg.is_item_shown('fx_fit_note')"}, {"action": "tutorial_tree"}], 1.5),
    ([{"check": "dpg.is_item_shown('reader_win')"}, {"py": "chrome.close_dialog('reader_win') or dpg.hide_item('reader_win')"},
      {"effect": "Rainbow"}], 0.5),
    # live output to the fake device on this machine, and the wiring test; the stream asks the device how it takes
    # one - the fake says nothing of Respect LED maps, so WLED's default: in logical order, its map applied there
    ([{"frame": "send"}, {"stream": "127.0.0.1:8770"}, {"wiring_test": "chase"}, {"wiring_test": "index"}, {"wiring_test": "part"},
      {"wiring_test": "output"}, {"wiring_test": "white"}, {"wiring_test": "off"}], 4.0),
    ([{"check": "app._stream_wiring is not None and app.stream_order() == 'logical'"},
      {"expect": ["messages", "in the device's own order"]}, {"stream": False}], 1.0),
    # the stream in E1.31 (sACN) from universe 3, then Art-Net from 0, kept for the device - each restarts it, the
    # health line names it and its rate (the fake keeps every universe: checked at the end), then back to DDP
    ([{"device": "127.0.0.1:8770"}, {"py": "app.set_stream_out(protocol='e131', universe=3)"}, {"stream": "127.0.0.1:8770"}], 2.5),
    ([{"check": "type(app.ddp).__name__ == 'E131Out' and app.ddp.universe == 3 and app.stream_out('127.0.0.1:8770') == ('e131', 3)"},
      {"expect": ["live_status", "E1.31 (sACN):"]}, {"expect": ["live_status", "fps sent"]},
      {"py": "app.set_stream_out(protocol='artnet')"}], 2.5),
    ([{"check": "type(app.ddp).__name__ == 'ArtNetOut' and app.ddp.universe == 0"}, {"expect": ["live_status", "Art-Net:"]},
      {"py": "app.set_stream_out(protocol='ddp')"}, {"stream": False}], 1.0),
    ([{"check": "app.ddp is None and app.stream_out('127.0.0.1:8770')[0] == 'ddp'"}], 0.2),
    # every send to a device, against the fake WLED: the script, the settings, the shape, the ledmap
    ([{"frame": "devices"}, {"device": "127.0.0.1:8770"}, {"scan": "all"}], 6.0),
    ([{"layout": "graph"}, {"graph_open": "fan.json"}, {"py": "app.send_script()"}], 6.0),
    ([{"expect": ["send_status", "the device is running it"]}, {"effect": "Rainbow"}, {"py": "app.push_settings()"}], 3.0),
    ([{"expect": ["edit_status", "Rainbow"]}, {"py": "app.send_shape(True)"}, {"py": "app.send_ledmap(True)"}], 4.0),
    ([{"expect": ["edit_status", "ledmap"]}], 0.5),
    # the device's wiring read over the geometry the studio has: a cube wired one way, its ledmap sent to the fake,
    # the studio's cube wired plainly again - the read brings the same wiring back, as the cube's own settings
    ([{"geometry": {"kind": "cube", "params": {"B": 16, "faces": "T,N,E,S,W", "rots": "1,0,3,2,0", "serpentine": True,
                                                   "vertical": False, "start_right": True, "start_bottom": False}}},
      {"py": "setattr(app, '_wired_map', app.project.geometry.ledmap()['map'])"}, {"py": "app.send_ledmap(True)"}], 2.0),
    ([{"geometry": {"kind": "cube", "params": {"B": 16}}}, {"py": "app.read_device_wiring()"}], 2.0),
    ([{"check": "app.project.geometry.kind == 'cube' and 'map' not in app.project.geometry.params"},
      {"check": "app.project.geometry.ledmap()['map'] == app._wired_map"},
      {"expect": ["messages", "faces T N E S W"]}, {"check": "dpg.does_item_exist('geom_read_wiring')"},
      # a matrix takes the device's ledmap as its map (WLED uses it over the 2-D setup)
      {"geometry": {"kind": "matrix", "params": {"w": 8, "h": 8}}}, {"py": "app.read_device_wiring()"}], 2.0),
    ([{"check": "(app.project.geometry.kind, app.project.geometry.w, app.project.geometry.h) == ('matrix', 48, 48)"},
      {"check": "app.project.geometry.ledmap()['map'] == app._wired_map"},
      # a shape's wiring is its own: the read says so and changes nothing
      {"geometry": {"kind": "shape", "params": {"parts": [_TREE]}}}, {"py": "app.read_device_wiring()"}], 2.0),
    ([{"expect": ["messages", "a shape's wiring is its parts' order"]}, {"check": "app.project.geometry.kind == 'shape'"},
      {"geometry": {"kind": "cube", "params": {"B": 16}}}], 0.5),
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
      {"ed_type": "this is not C++ ;"}, {"ed_key": ["Return", False, False]}, {"py": "app.edit_save()"}], 1.2),
    # the pane's own save is no change from outside: the watcher (twice a second) leaves the status alone - it said
    # "reloaded from disk" over the build's problem when the build failed before its next look (Linux, packaged)
    ([{"expect": ["edit_status", "box_fire.cpp saved"]}, {"py": "app.edit_build()"}], 12.0),
    ([{"expect": ["edit_status", "problem"]}, {"action": "undo"}, {"action": "undo"}, {"layout": "graph"}, {"graph_open": "fan.json"},
      {"device": "127.0.0.1:1"}, {"py": "app.send_script()"}], 8.0),
    ([{"expect": ["messages", "failed"]}, {"device": "127.0.0.1:8770"}], 1.0),
    # a build error on a line a node wrote is the node's (an Expression's typed C++): its problem, held in the
    # log, and the build's message goes to it - not to a line of a file nobody wrote; mended and built, clear
    ([{"layout": "graph"}, {"py": "app.gp.new('expr_smoke')"},
      {"py": "setattr(app, '_xe', app.gp.graph.add('Expression', (460, 380), {'expr': 'a * frobnicate(b)'}))"},
      {"py": "app.gp.rebuild()"}, {"py": "app.gp.compile()"}], 12.0),
    ([{"check": "app.gp.problems.get(app._xe, '').startswith('error: does not build')"},
      {"check": "f'problem:{app.gp._key()}:{app._xe}' in messages.HELD"},
      {"check": "(messages.HELD.get('build:', {}).get('node') or (0, 0))[1] == app._xe"},
      {"py": "app.gp.graph.nodes[app._xe]['params'].__setitem__('expr', 'a * b')"}, {"py": "app.gp.rebuild()"},
      {"py": "app.gp.compile()"}], 12.0),
    ([{"check": "not app.gp.problems.get(app._xe, '').startswith('error') and 'build:' not in messages.HELD"},
      {"check": "f'problem:{app.gp._key()}:{app._xe}' not in messages.HELD"}], 0.3),
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
    # the library: three banks (the project's graphs, the usermod effects, WLED's stock ones), thumbnails made on a
    # worker for every effect - each from a clean cube, hearing the synth - with a bar while they are; a preview
    # generated with its own bar; the frame docked and floated
    ([{"frame": "library"}, {"py": "library_ui._set_bank(app, 'stock')"}], 14.0),
    ([{"check": "dpg.get_item_label('lib_bank_stock').startswith('Stock (') and dpg.get_item_label('lib_bank_usermod').startswith('Usermod effects (')"},
      {"check": "len([k for k, v in app._lib_thumbs.items() if v]) > 150"},
      {"py": "library_ui._set_bank(app, 'graphs')"}, {"py": "library_ui.generate_previews(app, 1.0, only=['Rainbow'])"}], 0.3),
    ([{"check": "app._lib_gprog is not None and dpg.is_item_shown('lib_progress_row') and dpg.is_item_shown('lib_cancel')"}], 6.0),
    ([{"check": "app._lib_gprog is None"}, {"check": "not dpg.is_item_shown('lib_cancel')"},
      {"check": "'1 preview' in dpg.get_value('lib_status')"},
      {"dock": ["library", True]}, {"dock": ["library", False]}], 5.0),
    # S21 the node tutorials: Slew's page with its picture playing; Try it opens its graph live in the tutorials
    # project, the page beside it, the panel folded; a "Try this" change to an input, then to another lesson's
    # setting; Reset; Copy into my project - back in this run's project with the graph, the layout as it was
    ([{"py": "chrome.close_all_frames(app)"}, {"py": "setattr(app, '_tut_panel_was', app.prefs.get('graph_panel_open'))"},
      {"py": "reader_ui.open_doc(app, 'NODES.md', 'Slew')"}], 1.5),
    ([{"check": "reader_ui.S.doc == 'NODES.md' and len(reader_ui.S.anims) >= 5 and not reader_ui.S.side"},
      {"py": "reader_ui.follow(app, 'studio:try/slew')"}], 8.0),
    ([{"check": "app.project.path.endswith('node_tutorials') and app.gp.file == 'tutorial_slew.json'"},
      {"check": "app.eng.names[app.eng.idx] == 'Tutorial Slew' and app.gp.ext_sel == [2]"},
      {"check": "dpg.is_item_shown('reader_tut_row') and dpg.get_value('reader_tut_what') == 'Tutorial: Slew'"},
      {"check": "reader_ui.S.side and dpg.get_item_pos('reader_win')[0] > dpg.get_viewport_client_width() // 2 and room.folded(app)"},
      {"py": "setattr(reader_ui.S, 'pending', {'k': next(i for i in range(reader_ui.reader.heading_index(reader_ui.S.blocks, 'Slew'), "
             "len(reader_ui.S.blocks)) if reader_ui.S.blocks[i]['kind'] == 'img'), 'tries': 0})"}], 2.0),
    ([{"check": "any(a['frames'] and a['i'] > 0 for a in reader_ui.S.anims.values())"},
      {"py": "reader_ui.follow(app, 'studio:try/slew/1')"}], 1.0),
    ([{"check": "app.gp.graph.nodes[2]['inputs']['up'] == 40.0 and dpg.is_item_shown('props_fly')"},
      {"py": "reader_ui.follow(app, 'studio:try/wave/1')"}], 8.0),
    ([{"check": "app.gp.file == 'tutorial_wave.json' and app.gp.graph.nodes[4]['params']['shape'] == 'square'"},
      {"check": "app._tutorial['back'][0].endswith('smoke_run') and app._tutorial['node'] == 'Wave'"},
      {"py": "tutorials.reset(app)"}], 6.0),
    ([{"check": "app.gp.graph.nodes[4]['params']['shape'] == 'sine'"},
      {"py": "reader_ui._tut('copy', app)"}], 6.0),
    ([{"check": "app.project.path.endswith('smoke_run') and app.gp.file == 'wave_tutorial.json' and getattr(app, '_tutorial', None) is None"},
      {"check": "not dpg.is_item_shown('reader_tut_row') and not reader_ui.S.side and app.prefs.get('graph_panel_open') == app._tut_panel_was"},
      {"py": "chrome.close_dialog(reader_ui.TAG)"}], 0.5),
    # S22 live video: the test pattern into the engine's video slot from the VIDEO section, paused, stopped
    ([{"check": "dpg.does_item_exist('video_kind') and dpg.does_item_exist('video_play')"},
      {"py": "video_ui.start(app, 'test')"}], 0.8),
    ([{"check": "app.video_src is not None and app._video_n > 2 and dpg.get_item_label('video_play') == 'Pause'"},
      {"check": "'playing - test pattern' in dpg.get_value('video_msg')"}, {"py": "video_ui.toggle(app)"}], 0.3),
    ([{"check": "app.video_src.paused and dpg.get_item_label('video_play') == 'Play'"}, {"py": "video_ui.stop(app)"}], 0.3),
    ([{"check": "app.video_src is None and dpg.get_value('video_msg').startswith('stopped')"}], 0.1),
    ([{"graph_open": "gyro_sand.json"}, {"graph_export": None}, {"confirm": 0}, {"feature": ["imu", False]},
      {"graph_import": f"projects/{SMOKE}/export/gyro_sand.graph.json"}, {"confirm": 0}, {"export_usermod": True}], 3.0),
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
    # the project's settings in File > History (issue #5): listed, and the newest copy put back - the project opened again from it
    ([{"layout": "both"}, {"py": "chrome.show_history(app, 'project')"}], 0.5),
    ([{"check": "dpg.is_item_shown('history_win') and dpg.get_value('history_what').startswith(\"The project's settings\")"},
      {"py": "setattr(app, '_kept', __import__('native.history', fromlist=['versions']).versions(app.project, 'project', 'project'))"},
      {"check": "len(app._kept) >= 1"}, {"py": "chrome.show_history_changes(app, 'project', 'project', '.json', app._kept[0][0])"}], 0.5),
    # what changed since it, before it is put back (the saved time left out)
    ([{"check": "dpg.is_item_shown('history_diff_win') and dpg.get_value('history_diff_what').startswith(\"the project's settings\")"},
      {"check": "len(dpg.get_item_children('history_diff_rows', 1)) >= 1 and "
                "not any(str(dpg.get_value(t)).startswith('saved') for t in dpg.get_item_children('history_diff_rows', 1))"},
      {"py": "dpg.hide_item('history_diff_win')"}, {"py": "chrome._restore(app, 'project', 'project', '.json', app._kept[0][0])"}], 1.0),
    ([{"check": f"app.project.path.endswith({SMOKE!r}) and not dpg.is_item_shown('history_win')"},
      {"expect": ["messages", "settings restored"]}], 0.5),
    # a project.json that does not read (issue #5): kept aside as project.json.bad-<time>, said in a dialog and a held
    # problem, the project on its defaults - and nothing of it held once another project is open
    ([{"py": "(lambda d: (__import__('os').makedirs(d, exist_ok=True), open(__import__('os').path.join(d, 'project.json'), 'w').write('{broken')))"
             "(__import__('os').path.join(__import__('os').path.dirname(app.project.path), 'smoke_bad'))"},
      {"project": "smoke_bad"}], 2.0),
    ([{"check": "dpg.is_item_shown('confirm_dialog') and 'project:load' in messages.HELD"},
      {"check": "any(f.startswith('project.json.bad-') for f in __import__('os').listdir(app.project.path))"},
      {"py": "dpg.hide_item('confirm_dialog')"}, {"project": SMOKE}], 2.0),
    ([{"check": f"app.project.path.endswith({SMOKE!r}) and 'project:load' not in messages.HELD"}], 0.5),
]



def send(cmds, wait):
    """A step's commands, once the app has taken the last step's (never written over unread). False when
    the last step's were not taken in four minutes: the app has stopped taking commands, and waiting four
    more for each of the steps left kept a hung run going for hours (a macOS runner's first try)."""
    end = time.time() + 240
    while os.path.exists(CMD) and time.time() < end:
        time.sleep(0.2)
    if os.path.exists(CMD):
        return False
    scratch.write_whole(CMD, json.dumps(cmds))            # whole: the app takes it the moment it is there
    time.sleep(wait)
    return True


def make_films():
    """The S18 films: two sides of a small tree lit by the camera plan, as mp4s. False without ffmpeg."""
    import shutil
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    sys.path.insert(0, os.path.dirname(HERE))                  # the studio's own source, packaged app or not
    import numpy as np
    from native import camera_map as cm
    t = np.linspace(0, 1, 60)
    r = 40 * (1 - t) + 4
    P = np.stack([r * np.cos(t * 8 * np.pi), r * np.sin(t * 8 * np.pi), t * 120], 1)
    plan = cm.Plan(60, on=0.2, off=0.05)
    for path, ang, hide in zip(MAP_FILMS, (0, 90), ((5, 17), (30,))):
        frames = cm.synthetic_video(P, plan, ang, fps=30.0, size=(200, 200), hide=hide, seed=ang + 3)
        p = subprocess.Popen([ff, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "200x200", "-r", "30", "-i", "-",
                              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", path], stdin=subprocess.PIPE)
        for f in frames:
            p.stdin.write(f.tobytes())
        p.stdin.close()
        p.wait()
    return all(os.path.exists(p) for p in MAP_FILMS)


def main():
    try:
        sys.stdout.reconfigure(errors="replace")         # the app's lines can hold what a Windows console cannot print
    except Exception:
        pass
    if not scratch.DIR:
        print("smoke: no private scratch folder to drive the app through (native/scratch.py)")
        return 1
    if not make_films():
        print("no ffmpeg: the camera-map steps are left out")
        STEPS[:] = [s for s in STEPS if s not in MAP_STEPS]
    smoke_dir = os.path.join(ROOT, "projects", SMOKE)
    for d in (smoke_dir, os.path.join(ROOT, "projects", "smoke_bad")):
        if os.path.isdir(d):
            shutil.rmtree(d)                                  # a run that was stopped: started afresh
    tut_dir = os.path.join(ROOT, "projects", "node_tutorials")
    tut_had = os.path.isdir(tut_dir)                          # the tutorials' project: removed after only if this run made it
    caps_before = set(os.listdir(os.path.join(ROOT, "captures"))) if os.path.isdir(os.path.join(ROOT, "captures")) else set()
    STUDIO_FILE = os.path.join(ROOT, "projects", "studio.json")   # the prefs, and the last project: put back after
    saved_prefs = open(STUDIO_FILE, encoding="utf-8").read() if os.path.exists(STUDIO_FILE) else None
    if saved_prefs is not None:
        os.remove(STUDIO_FILE)       # from no settings, as a CI runner starts: frames docked by an earlier run take the room the steps measure
    from fake_wled import FakeWled                          # the device every send goes to, and the DDP receiver
    ddp = FakeWled(port=8770, ddp_port=4048).start()
    with open(LOG, "w") as log:
        # the console variant of the packaged app keeps its stdout, which is the log the test reads
        cmd = [EXE] if EXE else [sys.executable, "-u", "-m", "native.app"]
        env = dict(os.environ, STUDIO_NO_UPDATE_CHECK="1", STUDIO_NO_WELCOME="1", STUDIO_REMOTE_CONTROL="1")
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    early = None
    try:
        time.sleep(9 if not EXE else 30)                 # the packaged app unpacks itself first
        for k, (cmds, wait) in enumerate(STEPS):
            if proc.poll() is not None:
                early = f"the app exited early (code {proc.returncode}) before step {k + 1} of {len(STEPS)}"
                print(early); break
            if not send(cmds, wait):
                early = f"the app stopped taking commands: step {k} of {len(STEPS)} was never taken"
                print(early); break
        if early is None and proc.poll() is not None:
            early = f"the app exited early (code {proc.returncode}) during the last step"
    finally:
        proc.kill()
        time.sleep(1)
        if saved_prefs is not None:
            open(STUDIO_FILE, "w", encoding="utf-8").write(saved_prefs)
        shutil.rmtree(smoke_dir, ignore_errors=True)          # the run's project, and all it made in it
        shutil.rmtree(os.path.join(ROOT, "projects", "smoke_bad"), ignore_errors=True)    # the one with the broken project.json
        if not tut_had:
            shutil.rmtree(tut_dir, ignore_errors=True)
    text = open(LOG, encoding="utf-8", errors="replace").read()
    ddp.stop()
    print(f"e1.31: {ddp.e131_packets} packets, universes {sorted(ddp.e131_univ)[:3]}...; "
          f"art-net: {ddp.artnet_packets} packets, universes {sorted(ddp.artnet_univ)[:3]}...")
    print(f"ddp: {ddp.ddp_packets} packets, {ddp.ddp_frames} frames received from the stream; "
          f"the fake got {len(ddp.files)} file(s), {len(ddp.presets) - 1} preset(s), {len(ddp.cfg['timers']['ins'])} timer(s)")
    bad = [l for l in text.splitlines() if "Traceback" in l or "Error:" in l or "command file:" in l
           or l.startswith("command {")]                          # a step's command that raised: the rest of its step never ran
    if early:
        bad.append(early)
    if "remote control: write" not in text:
        bad.append("the app's output was not captured, or its remote control was off (no 'remote control: write' line): "
                   "a buffered stdout, the wrong exe, or STUDIO_REMOTE_CONTROL not reaching it")
    if ddp.ddp_frames < 10:
        bad.append(f"the DDP stream sent {ddp.ddp_frames} frames; 10 or more expected")
    # the cube's net in logical order, 6912 bytes, is 14 universes of 510 (the last 282): from 3 in E1.31, from 0 in Art-Net
    for name, univ, first in (("E1.31", ddp.e131_univ, 3), ("Art-Net", ddp.artnet_univ, 0)):
        if sorted(univ) != list(range(first, first + 14)):
            bad.append(f"the {name} stream's universes were {sorted(univ)}; {first}..{first + 13} expected")
        elif sum(len(univ[u]) for u in univ) != 48 * 48 * 3:
            bad.append(f"the {name} stream's universes held {sum(len(univ[u]) for u in univ)} bytes; {48 * 48 * 3} expected")
    if len(ddp.ddp_last) != 48 * 48 * 3:                 # the cube's whole net, in logical order - not its 1280 LEDs in wiring order
        bad.append(f"the last streamed frame was {len(ddp.ddp_last)} bytes; the 48 x 48 cube in logical order is {48 * 48 * 3}")
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
    for f in (set(os.listdir(os.path.join(ROOT, "captures"))) if os.path.isdir(os.path.join(ROOT, "captures")) else set()) - caps_before:
        if f.endswith(".zip"):                                  # the project zip the run made
            os.remove(os.path.join(ROOT, "captures", f))
    for name in ("/studio.bin", "/ledmap.json", "/geometry.bin"):
        if name not in ddp.files:
            bad.append(f"the fake device never received {name}")
    if bad:
        print("smoke: FAILED")
        print("\n".join(bad[:30]))
        # what the app did up to the first thing that went wrong, for a run nobody watched (a CI runner's log
        # is all there is): its lines from 60 before that one
        lines = text.splitlines()
        first = next((k for k, l in enumerate(lines) if "EXPECT FAILED" in l or "Traceback" in l or l.startswith("command {")), None)
        if first is not None:
            print(f"the app's lines {max(0, first - 60) + 1}..{first + 25} of {len(lines)}:")
            print("\n".join("  | " + l[:300] for l in lines[max(0, first - 60):first + 25]))
        if early:                                             # what the app said last
            print("the app's last lines:\n" + "\n".join("  " + l for l in lines[-40:]))
        return 1
    print(f"smoke: ok ({len(STEPS)} steps, log {LOG})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
