# Layered Laser Art Generator — Plan v1

Status: revised after review round 1 (art direction, fabrication/LightBurn,
architecture). The finding-by-finding outcomes are in `REVIEW_LOG.md`.
Research basis: `RESEARCH.md`.

## 1. Goal and differentiator
Generate layered artwork, delivered as **LightBurn-ready SVG**, that is
(a) **good art**, composed rather than merely sliced, and (b) **cuts and
assembles correctly the first time**.

Competing generators admit their output "needs cleanup before it will cut".
This app guarantees manufacturability **by construction**, shows a
fabrication report, and treats composition as a first-class engine rather
than leaving it to luck.

## 2. Users and deliverables
- **User:** a LightBurn owner with a diode or CO₂ laser, cutting 3 mm ply/MDF or cardstock.
- **Export bundle (zip):**
  1. **Sheet files (primary).** All physical layers nested onto the user's stock size, one `<g>` per physical layer, rotation limited to 0°/180° to keep grain consistent.
  2. **Per-layer SVGs (secondary)**, for people who arrange sheets themselves.
  3. **Accessory parts:** spacer rings, back panel, hanger plate, alignment jig, as SVG.
  4. **Assembly sheet (HTML, printable):**
     - stack order
     - per-layer preview
     - colour/finish plan
     - spacer plan
     - glue zones
     - the DFM and aesthetic report
  5. **Overlay preview as PNG only.** It is never an SVG, because a combined SVG cut by mistake cuts every layer on top of every other one.
  6. **Project file** (`.layered.json`), which re-creates everything exactly.
- **Not in v1:** native `.lbrn2`, laser control, accounts, text-to-image AI, vector import, three.js 3D view.

## 3. Core model: a layered scene graph
The round 1 art review showed that one depth field cut by thresholds
gives a contour-map look: parallel "onion-ring" edges with uniform reveals.
So the **core model is a stack of layers, each a composition of motif
instances**:

```
Project
 ├─ settings: material preset, construction mode, size, N, spacer plan, seed
 ├─ frame/aperture: shape + per-layer progression
 └─ layers[0..N-1]   (0 = back)
     └─ elements[]: motif instance
          ├─ kind:        ridge | treeline | tree | cloud | sun/moon | birds | grass | rocks | water | wave | figure | mandala-ring | field-band | ...
          ├─ silhouette:  polygon set (generated as vectors, never traced)
          ├─ edge style:  organic(fractal amp/freq) | faceted | geometric, detail scale
          ├─ interior cuts: windows, branch gaps, star holes, lace (first-class)
          ├─ textures:    score/engrave hatching (grass, bark, water lines)
          └─ anchor:      frame | below-layer | bridge-designed | acrylic-carrier
```

**Field generators** still exist, for topo maps, height reliefs, photo
planes and hand-painted depth. They are *one kind of layer source*. They
extract isolines from the continuous field with **marching squares**
(sub-pixel interpolation) and emit `field-band` elements. They are not the
universal model.

### 3.1 Construction modes
| | **Spaced shadow box** | **Glued stack** |
|---|---|---|
| Typical | scenes, lightboxes, paper | topo, relief, mandala, wood portraits |
| Floating parts | forbidden: designed bridges → hidden routed bridges → acrylic carrier | allowed if fully supported by the layer below; min island area; numbered parts |
| Frame | required; shape/aperture progression; width ≥ max(8 mm, spacer land + glue land) | optional |
| Registration | identical outer outline + jig | **locator scores** of layer i+1 scored on layer i, inset 0.5–1 mm (hidden after glue) + **stepped pins** through layers 0..k where layer k+1 covers them + optional outline jig |
| Hidden material | hosts bridges, glue pads, labels, start points | hosts labels, pins, glue |

## 4. Geometry engine (polygon-only)
- **One representation.** Integer polygons via **clipper2-ts** (BSL-1.0) `Paths64`, at **1 unit = 1 µm**.
  - Every generator's output is snapped to this grid before any boolean operation.
  - Joins are round, with ArcTolerance ≈ 2 µm.
  - Clipper sits behind a thin interface so clipper2-wasm can be swapped in if profiling calls for it.
- **No raster tracing.** Potrace is GPL in every JS/WASM port, so it is dropped. Procedural content is emitted as vectors directly, and field sources use marching squares.
- **Curves.** v1 exports polylines simplified to 0.01 mm tolerance, written to 3 decimal places. Optional Schneider Bézier fitting at export comes later, with error bound ε added to every DFM constraint.
- **Validation runs on exactly the geometry that is written to the file**, and it uses **post-kerf geometry** (offset by −kerf/2). The output itself is not kerf-offset, except for fit features such as peg holes, slots and spacer rings.

### 4.1 DFM enforcement algorithm (defined order)
Parameters come from the material preset: `w` = min solid width, `g` = min
gap, `r` = min reveal, `a_isl` = min island area, `a_hole` = min drop-out
hole area.

```
clean(A) = close_complement( open(A, w/2), g/2 )   // open: deflate→inflate; gap fix on complement
           → drop holes < a_hole (fill), drop islands < a_isl (remove or merge)

Glued (front→back):
  M'_{N-1} = clean(M_{N-1})
  M'_i     = clean( M_i ∪ inflate(M'_{i+1}, r) )      // nesting + min reveal by construction

Spaced (front→back):
  Vis_i    = visible design of layer i
  Cover_i  = ∪_{j>i} M'_j
  Hidden_i = deflate(Cover_i, w/2 + parallax_i)        // parallax_i = Σ spacer depth in front × tan(30°)
  M'_i     = clean( Frame_i ∪ Vis_i ∪ Bridges_i ∪ HiddenFill_i )   with HiddenFill_i ⊆ Hidden_i

Repeat until changed area < ε (cap 4 passes), then validate; any residual violation is a hard error shown in UI.
```

### 4.2 Validators (all run as a hard gate before export)
| Check | Method |
|---|---|
| Min width | `area(A_k \ open(A_k, w/2)) > ε`, excluding convex-corner loss ≤ (w/2)²(1−π/4) per corner (A_k = post-kerf) |
| Min gap | same on the complement inside the outer boundary |
| Bridge strength | width ≥ w × f(span), with f growing for spans > 10 mm |
| Min reveal | `M_{i+1} \ deflate(M_i, r)` is empty (shared outer outline excluded) |
| Islands | PolyTree components; spaced mode: everything connected to the frame component |
| Drop-outs | interior holes < a_hole flagged or filled |
| Acute corners | inner radius ≥ kerf; spike tips < 30° flagged |
| Detail density | cut length per cm² and count of < 2w features → heat warning |
| Closed paths | cut colour: all closed. Score/labels may be open |
| Duplicates | impossible by construction (one Positive-fill union per layer); asserted |
| Sheet fit | parts + margin fit stock; tiling suggested if art > bed |
| Stack depth | Σ measured thickness + spacers ≤ frame/rabbet depth |

### 4.3 Bridges (spaced mode)
1. **Designed bridges first.** Motifs carry their own connectors: sun rays, branch lines, a flock line for birds, cloud strands, grass blades, and tree trunks rooted in the frame.
2. **Hidden routing for the rest:**
   - Build a cost raster at 0.25 mm: low cost in `Hidden_i`, high cost in visible voids, forbidden across protected visible detail.
   - Grow connections like Prim's algorithm from the frame, using multi-source Dijkstra.
   - Smooth each path, offset it as an open path by w/2 with round caps, and union it into the layer.
   - Large or elongated islands get ≥ 2 bridges.
3. **Fallback:** an acrylic carrier layer, or a warning to the user.
4. Re-validate after adding bridges, since bridges create new gaps. Report the **visible-bridge count** and a **bridge-visibility score**.

## 5. Art direction engine
### 5.1 Composition rules used by the scene generators
- **Coulisse staging:** masses alternate left and right like theatre wings, and the gaps lead to a focal point in the deepest opening, often a light source at the back.
- **Skyline variety:** each layer's top edge differs in height, frequency and amplitude. Never stack lookalike ridges.
- **Scale diminution:** motifs shrink with depth, and detail density rises toward the front.
- **Edge detail by depth:** crisp and jagged at the front, smooth and simple at the back (atmospheric perspective applied to line).
- **Overlap:** edges cross behind each other, not just nest.
- **Horizon and negative space:** keep the horizon off-centre and leave about 1/3–1/2 of the area as sky or negative space.
- **Odd groupings and rhythm** in repeated elements.
- **Focal contrast jump:** one larger value step at the focal plane. A near-silhouette front layer is allowed.
- **Varied reveals:** a target coefficient of variation for reveals, not just a minimum. Non-uniform spacer plans are allowed, for example a deeper gap between foreground and midground.
- **Frame as art:** an aperture library (rect, arch, circle, window, heart, organic foliage vignette) with **per-layer progression**: the tightest aperture is at the front and they open toward the back. Foreground motifs can merge into the frame.
- **Classic devices:**
  - sun or moon as **concentric apertures through several layers**
  - "tunnel" as a frame mode
  - interior negative space (windows, branch gaps, stars)

### 5.2 Value / finish models
| Model | Use |
|---|---|
| Atmospheric (light back → dark front) | landscapes |
| Tunnel/glow (dark back → light front) | mandalas, focal glow |
| **Unpainted single species** | value from cast shadows only, so the shadow preview *is* the design tool |
| Stain gradient (dilutions of one dye) | wood |
| **Backlit** | brightness ∝ number of overlapping sheets (like a lithophane), computed in preview |
| Custom per-layer colours | paper stacks |

### 5.3 Aesthetic warnings (in the report, non-blocking)
- **Invisible layer:** the visible area V_i is below about 5% of the window.
- **Edges too close or parallel:** long runs of near-parallel edges on adjacent layers (contour look).
- **Edge-only contact:** tangent or "kissing" points between edges of different layers.
- **Edges in line with each other:** top edges of different layers coincide in height.
- **Repetitive skylines:** skyline frequencies on different layers are too similar.
- **Uniform reveals:** reveal variation is too low.
- **Crowding:** cut-density hotspots.
- **Focal point blocked:** the focal motif is occluded or has low contrast.
- **Visible bridges:** a count of bridges seen from the front.
- **Fragile-looking features:** features that are legal but read as fragile.
- **Accidental alignment:** silhouette edges landing exactly on the frame window edge or corners.

## 6. Preview
- **v1: a 2D shadow preview.** Each layer is rendered with a cast shadow offset by its spacer depth along an adjustable light direction, with blur.
  - Modes: colour plan, unpainted wood, backlit (sheet-count luminance).
  - This shows reveals and is the main design tool, especially for unpainted wood.
- **Later: a three.js 3D view** with an orbiting camera and real shadow maps.

## 7. Fabrication outputs
- **Colour/operation convention (fixed, documented, the same in every file):**

  | LightBurn colour | Operation |
  |---|---|
  | 00 `#000000` | engrave (fills/textures) |
  | 01 `#0000FF` | score (labels, locator lines, grain arrows, textures) |
  | 02 `#FF0000` | cut |

  - Elements are written in run order: engrave, then score, then cut. This should make LightBurn's layer list come out in that order [V].
  - The physical layer number is **never** encoded as a LightBurn colour.
  - Guide geometry is omitted.
- **SVG contract:**
  - `width/height` in mm, with a viewBox where 1 unit = 1 mm
  - `<path>` elements only, with absolute coordinates
  - no transforms, `<use>`, clipping, `<text>` or CSS
  - `fill="none"` and an exact stroke colour on every path
  - all cut paths closed
- **Labels:** a **single-stroke (Hershey-style) font** as open score paths. Text is set as paths with opentype.js (MIT) or built-in Hershey data. Each part gets its physical layer number, FRONT/UP, a grain arrow, and island part numbers, all placed in hidden or glue zones with min-width clearance.
- **Start points:** each path's start node is placed in a hidden zone or at a corner. The assembly sheet notes that LightBurn's "choose best start point" overrides this [V].
- **Cut order:** inner-first nesting across all layers on a sheet. The assembly sheet recommends checking it in LightBurn's preview and turning off "Reduce travel moves" if inner-first breaks.
- **Nesting:** a simple v1 algorithm (bounding-box/skyline packing with 0°/180° rotation).
  - Part gap = kerf + 2 mm; edge margin 5–10 mm.
  - Stock presets: 300×300, 400×400, 600×400, 20×12 in, or custom.
  - No common-line cutting. A no-fit-polygon nesting algorithm comes later.
- **Accessories:**
  - **Spacer rings** that follow the frame outline, with ring count = gap depth ÷ thickness, and a hidden width ≥ glue land.
  - A **back panel**.
  - A **doubled hanger plate** or sawtooth zone. Single-thickness keyholes in 3 mm ply tear out.
  - An **alignment jig**: an L-corner or outline pocket.
- **Thickness:** the user enters the **measured** thickness, and stack depth is computed from it.
- **Assembly sheet guidance:**
  - glue spots, not a film
  - stain before assembly
  - glue only raw wood
  - spray adhesive or glue dots for back panels
  - honeycomb-mark face down/back
  - transfer tape or pins for small parts
  - paper: hold-down needed, and a flare-up warning for air assist

## 8. Material and laser presets
Each preset records: thickness (measured), kerf, `w`, `g`, `r`, `a_isl`,
`a_hole`, minimum corner radius, bridge span factor, default N, air-assist and
hold-down notes, and speed inputs for the time estimate. Starting values are
**provisional until replaced by coupon results**:

| Preset | kerf | w | g | r | a_isl | default N |
|---|---|---|---|---|---|---|
| 3 mm ply, diode | 0.15 | 2.0 | 1.5 | 3.0 | 8×8 mm | 5 |
| 3 mm ply, CO₂ | 0.30 | 2.5 | 2.0 | 3.0 | 8×8 mm | 5 |
| 3 mm MDF, CO₂ | 0.25 | 2.0 | 1.5 | 3.0 | 8×8 mm | 5 |
| Cardstock 250–300 gsm | 0.10 | 1.5 | 2.5 | 2.0 | 6×6 mm | 9 |

## 9. Calibration coupon (about 80×100 mm, all items labelled with scored numbers)
1. **Kerf comb:** ten 10 mm bars; push them together and measure the total.
2. **Line-width ladder:** 0.5–3 mm in 0.25 mm steps, both along and across the grain.
3. **Gap ladder:** the same range.
4. **Bridge ladder:** width × span (5, 15 and 30 mm).
5. **Drop-out series:** holes and islands at 3, 5, 8 and 12 mm.
6. **Peg-hole fits:** nominal −0.2 to +0.3 mm in 0.05 mm steps.
7. **Acute spikes:** 15°, 30° and 45°.
8. **Dense-detail patch:** to check heat build-up.
9. **Single-stroke label legibility:** text at 2, 3 and 4 mm.
10. **Two-piece reveal test:** reveals of 0.5, 1, 2, 3, 4 and 6 mm, stacked on a spacer.
11. **Measured-thickness field:** results feed back into the preset.

## 10. Architecture
- **Self-contained `layered-laser/` folder** with its own `package.json` and licence: MIT, possible now that Potrace is gone. It shares nothing with the Python WLED studio. Moving it to its own repo is recommended once it exists.
- **TypeScript + Vite browser app**, fully local; Tauri packaging later for Windows.
- **Pure core** (`core/`, no DOM): geometry, generators, DFM, export.
  - Each stage is a pure function memoised by a hash of its parameters.
  - Heavy stages run in a Web Worker with cancellation and progressive resolution.
- **Determinism:** a seeded PRNG (no `Math.random`) and integer geometry.
- **Project file:** versioned JSON with the seed, parameters, overrides and painted depth as an embedded PNG. Undo is a history of parameter states, which is cheap because all geometry is derived.
- **Testing (Vitest):**
  - Property tests (fast-check) over random seeds and parameters, asserting the invariants: nesting, width, gap, reveal, connectivity, closed paths, sheet fit.
  - Golden tests that compare geometry by symmetric-difference area.
  - An SVG contract linter.
  - The DFM gate on every export.
- **UX:**
  - curated presets plus "randomise" with a seed, because good defaults beat sliders
  - per-element override (move, delete or regenerate a motif; move or delete a bridge)

## 11. Milestones
| # | Milestone | Done when |
|---|---|---|
| **M0** | Spikes | (a) Generated 3-part sheet SVG imports into LightBurn at exact size with the 3 colours on the right operations, groups preserved, inner-first working; layer-list ordering observed. (b) Palette 05–28 recorded from LightBurn's palette export. (c) Coupon cut on the user's machine; preset updated. |
| **M1** | Core + checker, test-first | Clipper wrapper, DFM algorithm §4.1, validators §4.2, SVG exporter + linter, property tests green |
| **M2** | **Landscape scene generator** (first consumer) | ridges/treelines/sun aperture/birds with coulisse + skyline variety + edge-by-depth; shadow-box mode with frame/aperture progression; designed bridges; 2D shadow preview; sheet nesting; spacers/back/hanger; assembly sheet; coupon generator → **v1 release** |
| **M3** | Hidden-route bridges + aesthetic warnings | §4.3 step 2, §5.3 |
| **M4** | Field sources + glued mode | marching squares; topo (noise/DEM) and relief; locator scores, stepped pins, island numbering |
| **M5** | Mandala + waves generators | radial motif library with interior cuts; wave-curl motifs |
| **M6** | Photo (assisted) | portraits/pets via luminance posterisation + subject segmentation; landscapes via Depth Anything V2 Small (Apache-2.0, **self-hosted model file**), 3–4 coarse planes, then "restyle plane as motif"; labelled as a starting point |
| **M7** | Polish | three.js 3D view, Bézier export, no-fit-polygon nesting, `.lbrn2` investigation |

## 12. Risks
| Risk | Mitigation |
|---|---|
| LightBurn import quirks | M0 spike on real LightBurn before M1. Linter enforces the contract |
| Scenes still look generic | Composition rules in §5.1, curated presets, per-element overrides, aesthetic warnings, side-by-side review against real bestseller patterns |
| DFM loop doesn't converge | Pass cap, then a hard error with location highlighted. Property tests across seeds |
| Bridges ugly | Designed bridges first, hidden routing second, visibility score, user editing |
| Photo mode disappoints | Shipped last, labelled assisted, tonal-band portrait style |
| Kerf/thickness variance | Measured thickness, coupon-calibrated presets, post-kerf validation |

## 13. Open questions for the user
1. Main material first: 3 mm wood or cardstock?
2. Laser: diode or CO₂? Bed size?
3. Is a landscape shadow box the right first generator, or do you want mandalas, topo maps or portraits first?
4. Browser app (later packaged for Windows) OK?
5. Keep in this repo under `layered-laser/` for now, or start a new repo?
