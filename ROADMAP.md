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
- [ ] **The smoke test in suites** (VJ, pads, sequence, devices...), so a change runs only its own; repeated
      one-liners become helpers.

## 2. Fewer places for state to hide (stability)
- [ ] **A runtime object per subsystem** in place of loose `app._x` attributes (about 240 of them across 38
      modules), each with an explicit `reset()` and `close()`. The VJ first, where the review rounds' bugs were.
- [ ] **One play clock that never jumps**: the render's hold under it, instead of each timer correcting for
      `clock.shifted()`.
- [ ] **Swallowed errors made visible**: the 192 bare `except Exception:` blocks log once (crash log or status
      line) instead of passing silently.

## 3. Split the largest files (maintainability)
- [ ] `graph_ui.py` (5,300 lines), `app.py` (4,300), `sequence_ui.py` (3,800): one responsibility per module.

## 4. Measure, then speed up (speed)
- [ ] **A frame-time overlay**: milliseconds per frame for the engine, each VJ deck, MilkDrop, thumbnails, the UI.
- [ ] **Shaders read back a frame late**, without blocking, so a heavy shader no longer stalls the studio.
- [ ] **MilkDrop's per-pixel equations on the GPU**, through the path MD2 shaders already use.

## 5. Easier to use (UI)
- [ ] **The pad action list grouped** (Deck A/B/C/Selected, Mix, Effect, Modulators), recent picks on top.
- [ ] **The pad panel's settings in reach**: CLIP and CAMERA without scrolling past the action list.
- [ ] **The selected deck at a glance**: a coloured border on it and on the pads that act on it.
- [ ] **A starter "live show" project** with pads, a clip pad and a camera pad already set up.
