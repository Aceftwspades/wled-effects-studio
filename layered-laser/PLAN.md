# Layered Laser Art Generator — Plan v2

Status: revised after two review rounds (5 independent reviewers). The
finding-by-finding outcomes are in `REVIEW_LOG.md`. Research basis:
`RESEARCH.md`.

## 1. Goal and differentiator
Make layered artwork, delivered as **LightBurn-ready SVG**, that (a) is
**good art**, composed rather than sliced, and (b) **cuts and assembles
correctly the first time**, at a known cost in material and laser time.

Competing generators admit their output "needs cleanup before it will cut".
This app:
- guarantees manufacturability by construction
- explains every problem in plain words, with a fix button
- produces the frame, spacers, nesting, bill of materials (BOM) and assembly instructions around **either its own generated art or the user's own layer files**

## 2. Users
The primary persona is a hobbyist or small seller using LightBurn on
Windows, with a 10 W diode (or CO₂) laser and a 400×400 mm bed, cutting
1/8" (3 mm) Baltic birch or MDF. They sell framed shadow boxes at craft
fairs, make 10–20 copies of a bestseller, and personalise with names and
dates. Paper users come second.

## 3. Releases and milestones
| # | Release / milestone | Contents | Done when |
|---|---|---|---|
| **M0** | Spikes (before any app code) | (a) script-generated test sheet SVG; (b) **mini coupon**: kerf comb, width/gap ladder, bridge ladder, reveal test; (c) user saves a **LightBurn template project** with layers 00 ENGRAVE / 01 SCORE / 02 CUT preset to their settings; (d) palette 05–28 recorded from LightBurn palette export | SVG imports at exact size; colours land on the right layers; groups kept; inner-first works; layer-list order observed; coupon cut, preset numbers recorded |
| **M1** | Core (test-first) | units/coords, Clipper wrapper, element provenance, `clean()` (§6.2), validators (§6.3), SVG exporter + contract linter, property tests | invariants hold over 1 000 random seeds; exporter output passes linter |
| **M2 → v0.5 "Bring your own layers"** | First shippable | per-layer SVG import; DFM report with plain-language fixes; shadow-box framing (§7.1, rectangular + 3 aperture shapes); spacer kit / rings / foam options; back panel; hanger plate; frame-size presets; nesting **by finish group** with copies count; BOM + cut-time panel; assembly sheet; cut-order and proof workflow; cheap aesthetic warnings (§8.3 tier 1); 2D shadow preview | user takes a purchased 5-layer design → cut-ready sheets + assembly sheet with no manual LightBurn layout |
| **M3 → v1 "Landscape generator"** | Generated art | landscape engine (§8.1) with themes *mountains/forest* and *sea/coast*; motifs **connected by construction only**; personalisation text (OFL stencil-friendly fonts, bridged to frame); Shuffle with thumbnail history; per-motif delete/regenerate (stable IDs); remaining aesthetic warnings; acceptance test (§8.4) | acceptance test passes |
| M4 | Free-floating motifs | hidden-route bridges (§7.3), bridge visibility score, bridge edit UI, acrylic-carrier layer, seasonal themes | — |
| M5 | Glued stacks + field sources | marching squares; topo (noise/DEM), relief; locator scores, stepped pins, island numbering, transfer-tape guidance | — |
| M6 | Mandala, waves generators | radial motif library with interior cuts; wave-curl motifs | — |
| M7 | Photo (assisted) | portraits: luminance posterisation + subject segmentation; landscapes: Depth Anything V2 **Small** (Apache-2.0, self-hosted file) → 3–4 planes → restyle as motifs | — |
| M8 | Polish | three.js 3D view, Bézier export, no-fit-polygon nesting, generated `.lbrn2` (community format) | — |

**Why v0.5 comes first:** most sellers already own layered SVGs. Their pain
is checking that a file will cut, then adding the frame, spacers, nesting and
cost. M2 delivers exactly the core strengths, months before the generator.
It also gives the generator a tested backbone.

## 4. Deliverables (per export)
- **Sheet SVGs (primary).** One file per physical stock sheet, holding the parts of one **finish group** (one paint or stain colour), one `<g id="L03_mid">` per part.
  - Named in cut order: `01_L05-FRONT_sheetA_walnut.svg`.
  - Each file can be downloaded individually, or as a zip.
- **Per-layer SVGs** (secondary).
- **Accessory SVGs:** spacer kit, back panel, hanger plate, alignment jig. Small parts are nested into offcut space where possible.
- **Overlay preview as PNG only.** It is never an SVG, because a combined SVG cut by mistake cuts every layer on top of every other one.
- **Assembly sheet** (printable HTML):
  - BOM
  - cut order
  - recommended settings per operation (from coupon results)
  - pre-cut checklist
  - stack diagram
  - per-layer previews
  - glue zones
  - finishing plan
  - glue and clamp guidance
  - hanging guidance
  - DFM and aesthetic report
- **Proof export:** the same sheets scaled to cardboard or cardstock thickness, for a cheap test run.
- **Project file** `.layered.json`: parameters + **resolved geometry** + generator version. Old projects reopen unchanged after app updates, and batch copies are exact.

## 5. Data model and conventions
- **Coordinates:** the core uses **SVG convention, y-down, origin top-left, 1 unit = 1 µm** (integers). Generators that think in heights (y-up) flip once at their output. Sheet rotation (0°, 90° or 180°) is baked into coordinates at nesting time.
- **Faces:** the laser scores the **top face**, and that face becomes the **front**; the honeycomb-marked face becomes the back. Mirroring a layer is never automatic. A `cutFace` field exists for future flip workflows.
- **Material:** `{name, measuredThickness_mm, kerf_mm, kerfBottomNote, w, g, r, islandMinArea_mm2, islandMinInscribed_mm, holeMinArea_mm2, minCornerRadius, bridgeSpanFactor, passes/speeds per op (from coupon)}`.
- **Stock vs bed:** `stock: {w, h, grainAxis: x|y, price}` and `bed: {w, h}`. The maximum art size is **min(bed, stock) minus margins**. No tiling in shadow-box mode, because the seam would show.
- **Stack:**
  - `artLayers[0..N-1]`: 0 is the **backmost art layer**, which may be a solid backdrop; N−1 is the front.
  - The back panel, spacers, diffuser and frame front are **accessories, not counted in N**.
  - `gaps[i]` sits between art layers i and i+1, plus `gaps[N-1]` in front of the front layer (glass clearance). Each gap is `{type: rings|kit|foam|blocks, depth_mm}`.
    - For `rings` and `kit` types, depth is snapped to a multiple of the measured thickness, and the UI shows the snapped value.
  - `frameLand_mm` (default 8): the hidden band behind the frame where spacers and glue go.
- **Elements:** `{id (stable), kind, layer, protected: bool, source: generator|import|user, geometry, anchor}`. Geometry stays tagged with its element until export, so damage can be traced back to a motif.
- **Size units:** shown in inches or mm (locale default), stored in µm.

## 6. Geometry engine
### 6.1 Principles
- **Polygon-only.** clipper2-ts (BSL-1.0) `Paths64` at µm, round joins, ArcTolerance 2 µm, behind an interface.
- **No raster tracing.** Potrace is GPL, so it is dropped. Generators emit vectors, field sources use marching squares, and imported SVG curves are flattened at 0.01 mm.
- **Generators must emit DFM-compliant geometry**, which the contract tests check. `clean()` is a safety net that reports what it changed. It is not a design tool.
- **Kerf-aware thresholds** on design geometry:
  - effective solid width `w_e = w + kerf`
  - effective gap `g_e = max(g − kerf, kerf)`

  Post-kerf, solids lose a kerf and gaps gain one. The validator independently checks the true post-kerf geometry (offset −kerf/2).
- **Pipeline order:** generate → snap → clean → (mode processing) → simplify (0.01 mm) → snap → **validate** → write. Validation runs on exactly what gets written.
- **Tolerances:** every "is empty" test means "empty after erosion by δ = 0.05 mm", which absorbs µm slivers and simplification noise.

### 6.2 `clean(A)` — thin-part removal, not plain opening
Plain morphological opening rounds every corner and erases the crisp,
faceted and jagged edges the art needs. Instead:

```
O  = open(A, w_e/2)
R  = A \ O                              // candidate thin material
for each component c of R:
   touches = number of separate contacts between c and O
   if touches == 0              → thin island: remove (if protected → error)
   if touches >= 2              → neck: remove (if protected → thicken to w_e instead)
   if touches == 1 and length(c) <= w_e
                                → corner cusp: KEEP
   if touches == 1 and length(c) >  w_e
                                → thin protrusion: thicken to w_e if protected, else remove
gap pass: same analysis on (Outline \ A) with g_e, resolving by ADDING material only
          (fill neck gaps, thicken plugs to w_e)
holes < holeMinArea filled; islands below islandMinArea / islandMinInscribed handled per mode
```

- After the first removal pass, every step only adds material. The area only grows, so the loop converges. It is capped at 4 passes.
- Convergence is not validity, so the validator still runs. Any residual violation is a **hard error** at a highlighted location.
- **Damage report.** For each element e: `damage(e) = e ∩ (A_before \ A_after)`, and the symmetric for additions.
  - If damage exceeds δ on a protected element (focal motif, designed bridge, personalisation text, user override), the generator is asked to regenerate that element, or a hard error is shown.
  - Damage to non-protected elements is listed with a highlight.
  - User overrides go through the same pipeline. If DFM changed one, the UI shows a diff with accept/revert, and export stays blocked while violations remain.

### 6.3 Validators (hard gate before export)
| Check | Method |
|---|---|
| Min width | `erode_δ( P \ open(P, w/2) ) = ∅`, where P is the post-kerf polygon. Cusps are allowed per §6.2 |
| Min gap | same on the complement within the outline |
| Bridge strength | per bridge element (provenance gives span L): width ≥ w·max(1, L / (10 mm))^½ |
| Reveal (glued) | `erode_δ( M_{i+1} \ deflate(M_i, r) ) = ∅`, outer outline excluded |
| Reveal (spaced) | visible set `V_i = M_i \ ∪_{j>i} M_j`; `erode_δ( V_i \ open(V_i, r/2) ) = ∅`, except edges tagged zero-reveal |
| Connectivity | spaced: every component connected to the frame; glued: every island fully supported by the layer below |
| Islands / drop-outs | area ≥ islandMinArea **and** inscribed width ≥ islandMinInscribed; waste holes < holeMinArea flagged |
| Acute corners | spikes < 30° flagged; inner radius ≥ minCornerRadius |
| Detail density | cut mm per cm² over a threshold → heat/char warning |
| Closed paths | cut colour only |
| Duplicates | impossible by construction (one Positive union per layer per op); asserted |
| Labels hidden | every label lies inside the hidden region (§7.4) |
| Sheet/stack fit | parts + margin fit stock; Σ thickness + gaps ≤ frame depth |

Error messages are written in plain language. Example: *"The bridge under
the left bird is 1.4 mm wide after cutting; your material needs 2.0 mm.
[Thicken] [Remove bird]"*

## 7. Construction
### 7.1 Shadow box (spaced) — v0.5 and v1
- `Frame_i = Outline \ Aperture_i`.
- **Aperture progression: the front aperture is the largest, and apertures shrink toward the back** by inset step `s_i`, so each deeper frame edge peeks out (stepped mat / tunnel look). Shapes: rect, arch, circle (v0.5); window, heart, foliage vignette (v1). Foreground motifs may merge into the frame.
- **Order of operations per layer:** art ∪ frame, then cut the concentric sun apertures and other through-holes, then clip to the outline.
- Each gap's spacers must lie behind `Frame_{i+1}` within `frameLand`. This is validated.
- **Spacer options:**

  | Option | Notes |
  |---|---|
  | **Spacer kit** (default) | strips/blocks nested into offcuts, plus a corner jig; least waste |
  | Full rings | strongest, most material; waste % shown |
  | Foam tape | documented |
  | 1/4" blocks | documented |

- **Hidden region** (used for labels, glue, start points and later bridges):

  `Hidden_i = ∪_{j>i} deflate(M'_j, d_ij · tan θ)`, with θ = 30°, where `d_ij` = Σ gaps between i and j + Σ thickness of the sheets in between.

- **Back panel**, **hanger plate** (doubled thickness; a single 3 mm keyhole tears out), and an optional standard-frame mode, where the art is sized to the inner dimensions of an 8×10, 11×14 or 12×12 in frame and its rabbet depth.

### 7.2 Glued stack — M5
- Recurrence, front to back: `M'_i = clean( (M_i ∪ inflate(M'_{i+1}, r)) ∩ Outline )`.
  - This guarantees support and reveal.
  - Growth adds up to (N−1)·r, so the report shows visible-area change per layer and warns above 15%.
- **Registration:**
  - **Locator scores:** the *outer boundary only* of layer i+1, inset 0.75 mm, scored on layer i, so nothing shows through interior cuts.
  - **Stepped pins:** through layers 0..k where layer k+1 covers them. Diameter comes from the coupon's peg-fit result.
  - Optional outline jig.

### 7.3 Bridges — M4 (v1 only uses connected-by-construction motifs)
1. **Designed bridges** are part of the motif: sun rays, branch lines, flock line, cloud strands, grass blades, trunks rooted in the frame.
2. **Hidden routing:**
   - Build a cost raster at 0.25 mm: low cost in `Hidden_i`, high cost in visible voids, forbidden across protected detail.
   - Grow connections like Prim's algorithm from the frame, using multi-source Dijkstra.
   - Smooth each path, offset it by w_e/2 with round caps, and union it in.
   - Use ≥ 2 bridges when the island's area or aspect ratio is large.
   - Re-validate afterwards.
   - Performance budget: under 2 s per layer on a low-end laptop. Coarsen the raster if needed.
3. **Acrylic carrier** as a fallback. Report the visible-bridge count and visibility score.

### 7.4 Labels and marks
- Scored labels (single-stroke Hershey font; layer number, FRONT/UP, grain arrow, part numbers) go only in:
  - **spaced:** `deflate(Hidden_i, label clearance)` for i < N−1
  - **glued:** `deflate(M'_{i+1}, margin)`
- **The front layer is never labelled.** The assembly sheet and file name identify it.
- Visible art-scoring (hatching) and hidden label-scoring share colour 01, but the report lists them separately.

## 8. Art engine (v1)
### 8.1 Landscape algorithm (concrete)
- **Layer plan.** For each art layer i, the theme preset gives:
  - horizon height `h_i` (rising toward the front)
  - amplitude `a_i`
  - fBm octaves
  - base frequency `f_i`, varied per layer so no two adjacent layers share frequency within ±20%
  - a **coulisse bias**: alternating left/right mass weighting
  - edge-detail scale (low at the back, high at the front)
- **Skyline.** A 1D fBm (seeded) is shaped by the bias window and combined with edge style: *organic* (fractal midpoint displacement) or *faceted* (decimate then straighten). The silhouette is the region below the skyline, unioned with the frame.
- **Stamps.** A parametric motif library: pine, deciduous tree, treeline strip, rock, grass tuft, house with window cutouts, sun/moon (concentric apertures across k layers, radius schedule rₖ = r₀ + k·s), cloud (fused to ridge or frame), bird flock on a designed line.
  - Stamps are placed with Poisson-disc sampling, scaled by depth (diminution), and kept in odd-numbered groupings.
  - Each stamp is emitted as DFM-valid geometry for the active material.
- **Focal point.** The deepest gap in the coulisse aligns with the focal motif (sun, moon, cabin). There is one larger value step at the focal plane.
- **Negative space.** The sky is kept at 1/3–1/2 of the window area.

### 8.2 Value/finish models
| Model | Use |
|---|---|
| Atmospheric (light back → dark front) | landscapes |
| Tunnel/glow (dark back → light front) | mandalas, focal glow |
| Unpainted single species | value from shadows only; the shadow preview is the design tool |
| Stain gradient (dye dilutions) | wood |
| Backlit (brightness ∝ number of overlapping sheets) | lightboxes |
| Custom per-layer | paper stacks |

The **finish group** of each layer drives nesting. The default is "finish
before cutting", meaning whole sheets are painted or stained first.

### 8.3 Aesthetic warnings (non-blocking)
- **Tier 1 (v0.5):**
  - invisible layer (V_i < 5% of window)
  - uniform reveals (reveal coefficient of variation too low)
  - long runs of near-parallel edges on adjacent layers
  - top edges of different layers coinciding in height
  - edges landing on the frame window edge or corners
- **Tier 2 (v1):**
  - repetitive skylines
  - crowding
  - focal point occluded or low contrast
  - visible bridges
  - legal but fragile-looking features
  - edges touching at a point

### 8.4 Acceptance test for "good art"
1. A fixed set of 20 seeds per theme passes every DFM check and the tier-1 and tier-2 thresholds automatically.
2. A blind side-by-side: 10 generated pieces against about 5 reference styles the user picks, rated by the user. v1 ships when the user would put at least 6 of the 10 on their fair table.
3. References are for calibration only. No preset copies a specific commercial design.

## 9. Preview
The 2D shadow preview is in v0.5:
- each layer is drawn with a cast shadow offset by `d · tan(light elevation)` along the light azimuth, then blurred
- modes: colour plan, unpainted wood, backlit sheet-count luminance
- an optional "show hidden region" overlay

The three.js view comes in M8.

## 10. Production workflow support
- **BOM / cost panel (before export):**
  - sheet count per stock size and finish group
  - spacer material
  - cut length per operation
  - **estimated time per sheet and total**, from coupon speeds and passes
  - material cost
  - optional "fair price" → hours and cost-per-piece warning
- **Cut order:** the **front layer first**, since it is the most detailed and most likely to fail, then backwards. Accessories come last.
- **Pre-cut checklist:**
  - masking tape against smoke stain
  - flatten or pin the sheet
  - focus
  - air assist (paper: hold-down, flare-up warning)
  - open the LightBurn template, then Import
  - check inner-first in Preview; turn off "Reduce travel moves" if it breaks
- **Assembly guidance:**
  - glue spots, not a film; raw wood only
  - drying and clamp/weight time
  - stain before cutting or before assembly
  - warp warning for painted thin ply
  - sand char lightly
  - glass or acrylic front and dust
  - hanger weight
  - order for removing masking tape
- **Batch:** a copies count when nesting, plus frozen resolved geometry in the project file.

## 11. LightBurn output contract
- **Colours:** 00 `#000000` engrave, 01 `#0000FF` score, 02 `#FF0000` cut.
  - Elements are emitted in run order (engrave → score → cut).
  - The physical layer number is never encoded as a colour.
- **SVG structure:**
  - width/height in mm, viewBox 1 unit = 1 mm, 3 decimal places
  - `<path>` only, absolute coordinates
  - no transforms, `<use>`, clipping, `<text>` or CSS
  - `fill="none"` and an exact stroke colour on every path
  - cut paths closed
  - start nodes placed in hidden zones where possible
- **The template `.lbrn2`** (user-saved in M0, generated in M8) holds the speeds and powers. The SVG carries only geometry and colour.
- **Re-check:** the M0 spike is re-run against each new LightBurn release, since 2.x changed import and added Quick Nest.

## 12. Material presets (provisional until coupon replaces them)
| Preset | kerf | w | g | r | island min | default N |
|---|---|---|---|---|---|---|
| 1/8" Baltic birch (3.0–3.2 mm), diode | 0.15 | 2.0 | 1.5 | 3.0 | 64 mm², 5 mm inscribed | 5 |
| 3 mm ply, CO₂ | 0.30 | 2.5 | 2.0 | 3.0 | 64 mm², 5 mm | 5 |
| 3 mm MDF, CO₂ | 0.25 | 2.0 | 1.5 | 3.0 | 64 mm², 5 mm | 5 |
| Cardstock 250–300 gsm | 0.10 | 1.5 | 2.5 | 2.0 | 36 mm², 4 mm | 9 |

The diode preset notes a tapered kerf: the bottom face is narrower.

**Full coupon** (generated from M2; the M0 mini version has items 1, 2, 4 and 10):
1. kerf comb
2. width ladder, along and across the grain
3. gap ladder
4. bridge ladder (width × 5/15/30 mm span)
5. drop-out series (3/5/8/12 mm)
6. peg fits (−0.2…+0.3 mm)
7. acute spikes
8. dense-detail patch
9. label legibility (2/3/4 mm)
10. two-piece reveal test (0.5–6 mm)
11. measured-thickness field

## 13. UX
- **Main controls:**
  - size (in/mm) or frame preset
  - layer count
  - frame/aperture style
  - material (with measured thickness)
  - spacer type and depth
  - theme
  - **Shuffle** (thumbnail history, no raw seeds shown)
  - finish model and colours
  - personalisation text
- **Advanced (collapsed):** kerf, w/g/r, island and hole limits, reveal CV, parallax θ, bridge span factor.
- **Construction mode** is not shown until M5.
- **Overrides in v1:** per-motif delete and regenerate only, keyed to stable IDs. Shuffle warns when it would discard edits.

## 14. Architecture
- **Self-contained `layered-laser/` folder**, with its own `package.json` and an **MIT** licence. It shares nothing with the EUPL Python WLED studio. Moving it to its own repo is recommended.
- **Stack:** TypeScript + Vite, fully local; Tauri packaging for Windows later.
- **Core:** a pure `core/` module, no DOM.
  - Each stage is a pure function memoised by a hash of its inputs.
  - Workers handle heavy stages, with cancellation.
  - Seeded PRNG; integer geometry.
- **Tests (Vitest):**
  - fast-check property tests for the invariants
  - generator contract tests (emitted geometry is DFM-valid)
  - golden tests by symmetric-difference area
  - SVG linter
  - DFM gate on export
  - performance budget test on a throttled CPU
- **Licences and selling:**
  - Users own their outputs and may sell both the pieces and the files.
  - Fonts: SIL OFL only, with licence files bundled; Hershey with its attribution notice.
  - Depth Anything V2 Small: Apache-2.0, with attribution. Base and Large are never shipped.
  - The import UI reminds users to check the licence of purchased designs.

## 15. Risks
| Risk | Mitigation |
|---|---|
| Scope/solo-dev, never ships | v0.5 cut; every milestone is shippable |
| Generated scenes lose to $3–5 Etsy files | BYO path first; personalisation + customisation as the selling point; acceptance test |
| LightBurn import or version drift | M0 spike, re-run each release; linter |
| `clean()` damages art | generators emit valid geometry; damage report; protected elements |
| Slow on cheap laptops | performance budgets, coarse rasters, workers |
| Generator updates change saved designs | resolved geometry + generator version in the project file |
| Warped sheets / kerf variance | measured thickness, coupon presets, post-kerf validation, flatten step |
| Wrong cut settings waste wood | coupon-derived settings, template project, proof export, front-layer-first |

## 16. Open questions for the user
1. Material first: 3 mm wood or cardstock? Laser type and bed size?
2. Is "bring your own layers" first (v0.5), then the landscape generator (v1), the right order for you?
3. Themes you want first beyond mountains/forest and sea?
4. Browser app (later packaged for Windows) OK?
5. Keep in this repo under `layered-laser/` for now, or start a new repo?
