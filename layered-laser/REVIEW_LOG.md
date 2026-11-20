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

## Round 2 — two red-team reviewers on PLAN v1
Reviewers:
- **R**: consistency and algorithm red team
- **U**: maker (10 W diode, 400×400 bed, craft-fair seller) + product manager

| # | Sev | From | Finding | Disposition in PLAN v2 |
|---|---|---|---|---|
| 36 | crit | R | `clean()` = plain opening rounds every corner and erases crisp/faceted edges (round-1 #12 hollow) | **Adopted.** Thin-part removal keeping corner cusps (§6.2) |
| 37 | crit | R | `clean()` on the union silently kills designed details (rays, flock lines, birds) | **Adopted.** Generators emit valid geometry; per-element provenance; damage report; protected elements regenerate or error (§5, §6.2) |
| 38 | crit | R | `clean()` ignores kerf, so the validator always rejects its output | **Adopted.** w_e = w+kerf, g_e = g−kerf thresholds (§6.1) |
| 39 | crit | R | No termination guarantee; open/close can oscillate | **Adopted.** After the first removal, add-only operations (area grows, so it converges), pass cap, validator still runs (§6.2) |
| 40 | crit | R | Aperture progression backwards (front tightest hides the rest) | **Adopted.** Front largest, shrinking toward the back (§7.1). Round-1 #11 wording corrected |
| 41 | crit | R | Labels on front face visible; locators show through cuts | **Adopted.** Top face = front; labels only in hidden regions; front layer never labelled; locators on outer boundary only (§5, §7.2, §7.4) |
| 42 | crit | R | M2 motifs need bridges that only arrive in M3 | **Adopted.** v1 motifs connected by construction only; routing moved to M4 (§3, §7.3) |
| 43 | crit | U | v1 too big to ship | **Adopted.** v0.5 "Bring your own layers" release before the generator (§3) |
| 44 | crit | U | No path for the user's own artwork | **Adopted.** Per-layer SVG import is v0.5 (§3) |
| 45 | crit | U | Cross-layer nesting breaks finish-before-cut workflow | **Adopted.** Nest by finish group; "finish before cutting" default (§4, §8.2) |
| 46 | crit | U | No BOM/cut time up front | **Adopted.** BOM/cost panel (§10) |
| 47 | crit | U | No speed/power setup help | **Adopted.** LightBurn template project (M0, generated in M8); coupon-derived settings on the assembly sheet (§11) |
| 48 | crit | U | Spacer rings waste material | **Adopted.** Spacer kit default; rings/foam/blocks options with waste % (§7.1) |
| 49 | maj | R | Spaced-mode reveal undefined (non-nested) | **Adopted.** Reveal on visible set V_i (§6.3) |
| 50 | maj | R | Glued inflate adds up and changes the art; unclipped | **Adopted.** Clip to outline; area-change report and warning (§7.2) |
| 51 | maj | R | Parallax formula wrong | **Adopted.** Per-covering-layer d_ij incl. sheet thickness (§7.1) |
| 52 | maj | R | Corner allowance only valid at 90°; sliver tolerance | **Adopted.** δ-erosion emptiness tests; explicit simplify→snap→validate→write (§6.1, §6.3) |
| 53 | maj | R+U | Overrides undefined; re-roll discards edits | **Adopted.** Overrides through the pipeline with diff and accept/revert; v1 = delete/regenerate with stable IDs; Shuffle warns (§6.2, §13) |
| 54 | maj | R | Data model gaps (spacer plan, land, N, a_isl units, layer 0) | **Adopted.** §5 |
| 55 | maj | R | No concrete landscape algorithm; no art acceptance test | **Adopted.** §8.1, §8.4 |
| 56 | maj | R+U | Milestone order (coupon after M0; modes in M1; warnings late; acrylic carrier unscheduled) | **Adopted.** Mini coupon in M0; M1 core-only; tier-1 warnings in v0.5; carrier in M4 |
| 57 | maj | U | No test-cut workflow | **Adopted.** Front layer first, proof export, pre-cut checklist (§4, §10) |
| 58 | maj | U | Real frame sizes; stock ≠ bed; tiling seams | **Adopted.** Frame presets, stock/bed separate, no tiling in shadow box (§5, §7.1) |
| 59 | maj | U | Batch production; generator drift | **Adopted.** Copies count; resolved geometry + generator version in project (§4, §10) |
| 60 | maj | U | Personalisation text | **Adopted.** v1 text motif, OFL fonts, bridged to frame (§3) |
| 61 | maj | U | One generator too narrow | **Adopted.** Themes on one engine; mountains/forest + sea in v1, seasonal in M4 (§3) |
| 62 | maj | U | Controls: show/hide, plain-language errors | **Adopted.** §13, §6.3 |
| 63 | min | R | Coordinates/y-down, grain axis, art vs label score, pin size, sun/frame order | **Adopted.** §5, §7.1, §7.2, §7.4 |
| 64 | min | U | Assembly additions, licence statement, file naming, diode taper | **Adopted.** §4, §10, §12, §14 |
| 65 | min | U | Missing risks (value prop, perf, drift, version, warp) | **Adopted.** §15 |
