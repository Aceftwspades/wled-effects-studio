# Review Log

## Round 1 — three independent reviewers on PLAN v0
Reviewers:
- **A**: art direction (layered paper/wood artist)
- **F**: fabrication/LightBurn (production engineer)
- **T**: architecture (computational geometry / browser engineer)

| # | Sev | From | Finding | Disposition in PLAN v1 |
|---|---|---|---|---|
| 1 | crit | A | One nearness field + thresholds gives "onion-ring" contour art; scenes need layers made of distinct objects | **Adopted.** Core is a per-layer scene graph of motif instances (§3); fields are one layer source |
| 2 | crit | A | "Interior detail belongs in engraving" is wrong; negative space is half the papercut look | **Adopted.** Interior cuts first-class; engrave/score textures as art (§3). RESEARCH corrected |
| 3 | crit | T | Raster cleanup → separate Potrace traces breaks nesting/width invariants (double-traced shared edges, curve-fit thinning) | **Adopted.** Polygon-only engine; vectors generated directly; marching squares for fields; validate exported geometry (§4) |
| 4 | crit | T | Potrace is GPL in all JS/WASM ports | **Adopted.** Potrace dropped; app MIT; VTracer (MIT) is fallback if ever needed |
| 5 | crit | T | Cleanup order undefined; opening/closing/re-nesting undo each other | **Adopted.** Defined front→back algorithm with reveal built in, pass cap (§4.1) |
| 6 | crit | F+T | Kerf "not needed for stacking" half-right: widths lose a full kerf, gaps gain one | **Adopted.** Validate post-kerf geometry; compensate fit features only (§4). RESEARCH corrected |
| 7 | crit | F | Pins through nested glued stack show on top; "identical outline" impossible for relief | **Adopted.** Locator scores, stepped pins, jig (§3.1) |
| 8 | crit | F | Combined overlay SVG is a fire/waste hazard | **Adopted.** Overlay is PNG only (§2) |
| 9 | crit | F | Glued islands are loose parts that fall into the honeycomb or tip up; small drop-outs too | **Adopted.** a_isl, a_hole, part numbering, transfer tape note (§4.1, §7) |
| 10 | maj | A | Floating sky elements: auto-tabs ugly | **Adopted.** Designed bridges first, sun-as-aperture, acrylic carrier, visibility score (§4.3, §5.1) |
| 11 | maj | A | Frame treated as plain rectangle | **Adopted.** Aperture library + per-layer progression (§5.1) |
| 12 | maj | A | Edge quality: traced+opened edges look melted | **Adopted.** Edge styles per motif; edge detail by depth (§3, §5.1) |
| 13 | maj | A | Composition rules incomplete | **Adopted.** Coulisse, skyline variety, scale diminution, overlap, horizon, rhythm (§5.1) |
| 14 | maj | A | Reveal minimum alone gives mechanical look; spacing can be non-uniform; paper layer counts higher | **Adopted.** Reveal-CV target, spacer plans, paper default N=9 (§5.1, §8) |
| 15 | maj | A | Unpainted wood → shadows are the design; backlit = sheet-count luminance; focal contrast jump | **Adopted.** Value models (§5.2); shadow preview moved into v1 (§6) |
| 16 | maj | A | Aesthetic checks needed | **Adopted.** §5.3 warnings |
| 17 | maj | A+T | Photo depth → terraced mush | **Adopted.** Portraits via luminance posterisation + segmentation; depth only for coarse planes; last milestone (M6) |
| 18 | maj | F | Colour/operation convention unspecified; don't conflate sheet with LightBurn layer | **Adopted.** 00 engrave / 01 score / 02 cut, emitted in run order (§7) |
| 19 | maj | F | Closed-path rule conflicts with labels; fill-engraved text chars badly | **Adopted.** Single-stroke font, open score paths; closed rule on cut only |
| 20 | maj | F | Sheet workflow is the real pain point | **Adopted.** Nested sheet files primary, stock presets, 0/180° grain, tiling (§2, §7) |
| 21 | maj | F | Spacers/frame/hanger not designed; nominal thickness drifts | **Adopted.** Accessories + measured thickness + depth check (§7, §4.2) |
| 22 | maj | F | Heat/char in dense detail; bridge strength depends on span | **Adopted.** Density warning, span-dependent bridge rule, corner radius (§4.2) |
| 23 | maj | F | Paper needs its own profile | **Adopted.** Material/laser presets (§8) |
| 24 | maj | T | Clipper precision | **Adopted.** Paths64, 1 µm, snapping, ArcTolerance (§4) |
| 25 | maj | T | Validator methods unspecified | **Adopted.** §4.2 table |
| 26 | maj | T | No bridge routing algorithm | **Adopted.** Cost raster + Prim/Dijkstra, parallax-eroded hidden region (§4.3) |
| 27 | maj | T | Architecture: project file, determinism, workers, tests | **Adopted.** §10 |
| 28 | maj | T | Prefer clipper2-ts over wasm (sync, no manual delete) | **Adopted**, behind an interface |
| 29 | maj | T | "Fully local" vs HF CDN model download | **Adopted.** Self-host model file (M6) |
| 30 | min | T+A | v1 too wide; first generator choice | **Adopted.** v1 = M0–M2 with landscape scene (bands span edge-to-edge, so connect to the frame by construction); three.js, photo, vector import cut from v1. *Partially adopted:* A suggested topo first; topo moved to M4 because it needs glued mode, and landscape exercises the shadow box, which is the bestseller |
| 31 | min | F | Start points, cut-order caveats, precision, face side, warp notes | **Adopted.** §7 |
| 32 | min | T | Labels/holes need constraints + font licence | **Adopted.** Hidden-zone placement, opentype.js/Hershey (§7) |
| 33 | min | T | Separate package/licence from the EUPL Python studio | **Adopted.** Self-contained folder now, own repo recommended (§10) |
| 34 | min | A | Reveal number unsourced; 3–6 mm reads well on ply | **Adopted.** r = 3 mm default for wood; reveal row on coupon |
| 35 | min | F | Coupon contents | **Adopted.** §9 (11 items) |
