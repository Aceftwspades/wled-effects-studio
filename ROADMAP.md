# Roadmap: stability, maintainability, speed, ease of use

The next round of work after 1.23.1, in the order it is being done. Each item is ticked when it is on `main`.

## 1. Catch CI's failures before a push (maintainability)
- [x] **A pre-push check** (`python tests/prepush.py`): every `tests/test_*.py` as CI runs it, then again under
      the conditions only CI had: a held clock far from zero (a runner's long uptime), no ffmpeg (the packaged
      Windows runner), no OpenGL (the Windows and ARM Linux runners). 1.23.1 hit four CI failures that only
      these conditions show.
- [x] **Smoke checks wait for a condition, not a time**: fixed waits flaked three times in the 1.23.1 release.
      A step whose next batch opens with checks now polls them (the remote's `until`) instead of sleeping: the
      local run went from ~674 s of sleeps to 391 s in all.
- [x] **The smoke test in suites** (VJ, pads, sequence, devices...), so a change runs only its own; repeated
      one-liners become helpers. `python tests/smoke_app.py -s vj` runs the opening steps and one of twelve
      suites, each passing alone (a suite's `PREP` sets up what the ones before it would have left); the
      ~430 `__import__('native.x', ...)` in its steps are plain names the remote's hooks know.

## 2. Fewer places for state to hide (stability)
- [x] **A runtime object per subsystem** in place of loose `app._x` attributes (about 240 of them across 38
      modules), each with one default per field and a `forget()`. The VJ (`native/vj_state.py`, ~70
      attributes), the pads with their clip editor (`native/pads_state.py`, 27), the show and its timeline
      (`native/seq_state.py`, 35); the modulators (`modulate.state`), MIDI and OSC (`midi_ui.state`) and the
      device frames (`device_ui.state`) in their own modules, as only they use them. The graph editor's is
      already its `GraphPanel` (`app.gp`). The library's and the shape
      editor's followed in section 6.
- [x] **One play clock that never jumps**: the render's hold under it, instead of each timer correcting for
      `clock.shifted()`. Released, the clock runs on from where the render left it; the corrections are gone.
- [x] **Swallowed errors made visible**: the 192 bare `except Exception:` blocks log once (crash log or status
      line) instead of passing silently. `oops.swallowed()` says each place once in the studio's log and counts
      the rest (in a problem report's `carried_on.txt`); the expected ones (an empty queue, a device not there,
      a graph that is not scriptable) catch exactly that and stay quiet.

## 3. Split the largest files (maintainability)
- [x] `graph_ui.py` (5,300 lines), `app.py` (4,300), `sequence_ui.py` (3,800): one responsibility per module.
      Done: `sequence_ui.py` to 2,580, its sending (`seq_send`), audio tracks (`seq_audio`), sections
      (`seq_sections`), timecode (`seq_timecode`) and automation recording (`seq_record`) in modules of their own.
      `graph_ui.py` to 2,490: its add menu, node actions, field widgets (modulation ranges, XY pads, colour ramps),
      overlays, problems and sub-graphs as mixins of `GraphPanel` (`graph_addmenu`, `graph_actions`, `graph_fieldkit`,
      `graph_overlays`, `graph_problems`, `graph_subs`), beside the five it already had.
      `app.py` to 2,100: where the panes sit (`app_layout`), the mouse and keys (`app_input`), the code pane's tools
      (`app_code`) and projects (`app_projects`) as mixins of `App`; they never import `native.app`, which runs as
      `__main__` (a second copy), so its shared sizes moved to `app_layout`.

## 4. Measure, then speed up (speed)
- [x] **A frame-time overlay**: milliseconds per frame for the engine, each VJ deck, MilkDrop, thumbnails, the UI.
      The footer's stats popover lists where the time goes (`native/frametime.py`): the frame's polls, sim step,
      views and interface, each with what was measured inside it - the engine, each VJ deck (marked MilkDrop or
      shader), the VJ's thumbnails - and the library's thumbnail worker beside them.
- [-] **Shaders read back a frame late**, without blocking, so a heavy shader no longer stalls the studio.
      Measured, not done: deck shaders already run a frame behind on their own thread. A pixel-buffer readback
      a frame later saved nothing on an Intel UHD 630 - the driver runs queued work only once something waits
      on it, even after a glFlush (render 0.01 ms, the wait the GPU's whole 11-27 ms either way). MilkDrop 2's
      warp shader is feedback and must be waited for; its composite could be a frame late, but on this driver
      that moves the wait, it does not remove it.
- [-] **MilkDrop's per-pixel equations on the GPU**, through the path MD2 shaders already use.
      Measured, not done: over the 23 bundled presets at 320 x 180 the per-pixel equations (a 32 x 24 mesh in
      numpy) do not show among the costs. A MilkDrop frame's time goes to custom shapes drawn on the CPU (36%),
      the MD2 shaders (23%), the feedback's bilinear resample (18%), blurs, waves and echo (8% each). The
      targets worth it instead: the shapes, and the feedback warp on the GPU for presets without a warp shader.

## 5. Easier to use (UI)
- [x] **The pad action list grouped** (Deck A/B/C/Selected, Mix, Effect, Modulators), recent picks on top.
      Each group under a header row (`pads_ui.group_of`), the last six picks first (prefs `pad_recent`).
- [x] **The pad panel's settings in reach**: CLIP and CAMERA without scrolling past the action list.
      The list folds once a control drives something - what the action needs (look, clip, camera, range) right
      under it - and **Change what it drives** opens it again; a pick folds it.
- [x] **The selected deck at a glance**: a coloured border on it and on the pads that act on it.
      Each deck a colour (`vj.DECK_RGB`: A blue, B orange, C violet): the selected deck's frame in it, every
      deck's title in its own, and a strip along each pad that acts on a deck (the selected deck's: as selected now).
- [x] **A starter "live show" project** with pads, a clip pad and a camera pad already set up.
      File > Project > New live show project... (`native/live_show.py`): two looks on decks A and B, the Live bank
      and a Show bank (deck pickers, knobs on the selected deck, a Clip pad with a starter clip ffmpeg makes, a
      Camera pad on the first webcam found), the VJ and the pads opened.

## 6. Next round: MilkDrop's real costs, the last loose state
- [x] **MilkDrop's custom shapes ~1.9x quicker**, the same pixels (off by 4e-6 at most over every bundled preset's
      shapes, replayed through the old and new code): each instance works on the pixels inside it only, a channel at a
      time (numpy is ~10x slower broadcasting over a 3-wide last axis), a polygon of up to 16 sides finds its edge
      from its sides' normals instead of arctan2 and cos over its box, and an instance no longer copies the frame or
      re-reads the preset's variables. Feeling well 256 -> 87 ms a frame; all 23 presets 1,477 -> 1,031 ms.
- [x] **The bilinear sampler** (`vj_looks.sample`: the feedback warp, textured shapes, every video look) a channel
      at a time and its wrap by fmod: 1.3-1.5x, bit for bit the same.
- [-] **The feedback warp on the GPU** for presets without a warp shader. Measured, not done: with the sampler above,
      every bilinear read in MilkDrop (the warp, textured shapes, video) is 13% of a frame over the 23 presets
      (5.0 of 38.3 s profiled), while the MD2 shaders' GPU passes are 27% (10.5 s) - nearly all of it waiting on the
      GPU. A warp pass there would add that wait to the presets that have no GPU pass now, to save part of 13%.
- [x] **The library's `_lib_*` and the shape editor's `_shape_*`** in a state object each, as the others:
      `library_ui.state` (24 fields; its thumbnail and preview workers' queues, jobs and progress) and
      `native/shape_state.py` (18; `PROJECT` names what another project's opening drops). The selected part read
      as 0 in one place and -1 in three; it is -1 everywhere (the first part is still what a fresh selection
      shows). `_shape_checks` was written and never read: gone.
