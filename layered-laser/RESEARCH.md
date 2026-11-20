# Layered Laser-Cut Artwork — Research Dossier

Research for a new application that generates layered artwork as SVG files
for LightBurn. Researched 2026-11-20.

**Confidence tags** used throughout:
- **[S]** sourced: stated by one or more sources listed at the end.
- **[C]** consensus: several independent practitioner sources agree.
- **[D]** derived: my own reasoning or engineering judgment, not taken from a source.
- **[V]** must be verified on a real machine or in LightBurn before we rely on it.

Note on method: this session's network allowed web search but blocked direct
page fetches (DNS failures for LightBurn docs/forum, maker blogs). The facts
below come from search-result excerpts of those pages. Anything thin is
marked [V].

---

## 1. What layered laser-cut art is

A layered piece is a stack of flat sheets (wood, paper, acrylic, card), each
cut to a different outline. Depth comes from the stack: the edges of upper
layers cast shadows on lower layers, and the eye reads each sheet as a
plane in space [C]. Common genres:

| Genre | Typical look | Notes |
|---|---|---|
| **Shadow box / paper-cut scene** | Landscape or scene seen *through* framed cutout layers, back layer is sky | Layers separated by spacers at the frame; every layer needs a border frame [C] |
| **Stacked relief (glued)** | Layers glued face-to-face, upper layers smaller | Topographic maps, mandalas, animal portraits [C] |
| **Layered mandala** | Radially symmetric, each layer more open toward the front | 2–6 mm material common [S] |
| **Topographic / contour map** | Each layer = one elevation band | Many dedicated tools exist (TopoStack, topo-layers, Maperivo) [S] |
| **Backlit lightbox** | Shadow box with LEDs behind / between layers | Diffuser needed; LED hotspots if too close [S] |
| **Painted/stained layered wood** | Layers finished in a value gradient | Stain combines with layers below, paint covers [S] |

---

## 2. Visual design principles (what makes it *good*)

### 2.1 Depth planning
- **Split the scene into foreground, midground and background** [C]. The 3D effect comes from this separation, not from the number of sheets.
- **Give each layer its own job** (e.g. back = hills, middle = trees, front = flowers) and **don't repeat the same shapes on every layer** [S].
- **Per-zone cutting rule** from paper shadow-box practice [S]:
  - *Back layer*: uncut, or a simple background (sky, sun).
  - *Middle layers*: cut away the margins around elements that should come forward.
  - *Front layer*: follows the outlines of the main subjects (the focal point).
- Typical structure: a solid background, 1–3 background cutout layers, and 2–3 front layers including one focal layer [S].

### 2.2 Layer count
- Consensus range is **3–8 layers**. Simple signs use 2–3, shadow boxes 5 or more [C].
- 5 layers is the most common recommendation for a clear depth effect; 5–9 is still easy to assemble; 10+ gives dramatic, atmospheric depth but is hard for beginners [C].
- Layer count is limited by frame depth: 10 layers in a 1-inch frame will press the front layer against the glass [S].
- **App default: 5 layers, range 2–12** [D].

### 2.3 Value and colour progression
- **Value matters most** for readability in layered paper art [S].
- **Atmospheric perspective**: distant layers lighter, cooler, less saturated, lower contrast; front layers crisp, dark and high-contrast; **shift value by a small, even step per layer** [S].
- Conflict in sources: some craft guides say "darkest at the back". Two coherent conventions exist [S]:
  1. **Atmospheric** (light back → dark front): reads as landscape distance. Best for scenes.
  2. **Tunnel / glow** (dark back → light front): reads as depth into a hole, or a glowing focal point. Best for mandalas and backlit work.
  → The app should offer both as palette presets [D].
- Saturation drops and hue cools with distance [S].
- **Back layer colour matters**: it shows through every cutout, and plain white or raw card makes the whole piece look washed out [S].
- For wood, **dyes and stains** keep grain visible and combine across coats; diluting one colour gives a monochrome gradient [S]. Paint covers fully.

### 2.4 Composition and readability
- One clear **focal point** on a front layer [S].
- **Avoid overcrowding.** Clutter destroys impact, and beginners should avoid dense cityscapes and highly detailed characters [S].
- **Check from the front after each layer**: important details must stay visible and must not be hidden by a layer in front [S]. → In the app this becomes an automatic *occlusion check* [D].
- **Silhouette readability** [D]: a layer is seen mostly as a silhouette against the layer behind it, so each layer's outline should be recognisable on its own. *(Corrected in review round 1: interior negative space, such as windows, branch gaps and star holes, is half the papercut look and essential for backlit work. Cut it, within min-feature rules. Engraving and scoring add texture on top.)*
- **Reveal width** [D]: the visible ledge between a layer's edge and the edge of the layer behind it. Under about 1–2 mm it disappears or looks like a cutting error. Generous, varied reveals read as depth. Nothing I found states a number, so this needs a physical test [V].
- **Overlap** is the strongest depth cue: front shapes should partly cover the shapes behind them [D, standard pictorial depth cue].

### 2.5 Spacing and lighting
- **Spacing is what separates professional work from beginner work.** Treat each layer as a separate plane, not a sheet glued on the last [S].
- Spacers: about 3 mm between layers is common, as are 1/4" scrap blocks or foam strips at the border [S]. Spacers must not be visible from the front [S].
- **Uniform spacer heights give even shadow lines** [S].
- Raised layers cast their own shadows, and side or top light makes the depth dramatic [S].
- Backlit builds:
  - LEDs too close to the diffuser show as hotspots [S].
  - In shallow boxes use a denser strip or a second diffuser rather than moving the LEDs closer [S].
  - Diffusers can be paper, frosted acrylic or fabric [S].
  - A translucent or tissue layer can mute regions such as water reflections [S].

---

## 3. Fabrication constraints (what makes it *cuttable and buildable*)

### 3.1 Minimum feature sizes
| Rule | Value | Source |
|---|---|---|
| Smallest detail ≥ material thickness | wood/acrylic general rule | [C] (Handyloom; metal DFM sources say 1–1.5×t for holes) |
| Webs/bridges ≥ material thickness | prevents overheating & breakage | [S] |
| Section widths ≥ 2×t (conservative) | structural | [S] (metal-oriented) |
| Paper: thinnest reliable line | **1.5–2 mm** | [S] Glowforge community |
| Paper: gap between thin cuts | **2–3 mm** | [S] |
| Features below kerf width are lost | — | [S] |
| Feature spacing | ≥1 mm, 2.5 mm preferred | [S] Purdue lab |

→ App rule [D]: `min_feature = max(material_floor, k_t × thickness)`, with
material floors of about 1.5 mm for paper and about 2 mm for 3 mm ply, and
k_t defaulting to 1.0. This applies to both solid widths and gaps. All values
are user-editable and should be calibrated with a test-coupon generator [V].

### 3.2 Kerf
- Diode laser in thin ply: **about 0.08–0.20 mm**. CO₂ in 2–5 mm ply: **about 0.26–0.62 mm** [S].
- For stacked art, kerf shrinks every outline by about kerf/2. Because all layers shrink the same way, alignment is unaffected [D]. *(Corrected in review round 1: feature sizes are affected. Every solid loses a full kerf in width and every gap gains one, so on CO₂ a 2 mm bridge becomes about 1.5 mm. Diode kerf is also tapered. **DFM checks must run on post-kerf geometry**, while the output stays un-offset except for fit features: inlays, slots, peg holes and press-fits.)* Measure your own kerf [S].
- LightBurn's own kerf offset can misbehave on mixed open and closed paths [S]. One more reason to emit only closed paths [D].

### 3.3 Islands, bridges and support
- **Shadow-box (spaced) layers: nothing may float.** Every piece must connect to the frame [S]. Pieces that fall out of a cut layer are lost.
- **Glued stacks:** a piece on an upper layer can be an island as long as it sits fully on material in the layer below, because it gets glued down [D]. It still needs **registration**, since it has no frame to locate it.
- Commercial generators (Atomm) **add bridges to tie islands back** automatically [S].
- No source gave a bridge width, so the minimum-feature rule applies [D/V].
- **Key derived insight [D]:** in a spaced shadow box, material on a deeper layer that is *hidden behind a front layer* is invisible. Bridges and extra hidden material can be **routed behind front-layer material** so they add strength without being seen. This is an optimisation few hand designers bother with, and software can do it automatically.

### 3.4 Glue-up, alignment, warping
- Every layer must be **exactly the same outer size** for alignment [S].
- Alignment options [S]:
  - alignment marks
  - reference corners
  - **pin holes / dowels** through hidden areas
  - a **jig around the outline**, outside edges first
  - precision alignment pegs for many-layer topo builds
- **Glue needs raw wood**: it doesn't bond to ink or paint. Plan unpainted glue zones [S].
- Keep glue at least about 12 mm (1/2") back from visible painted edges to avoid squeeze-out [S].
- **Warping**:
  - Water-based glue on thin sheets is the main cause, so use as little as possible [S].
  - Assemble at the humidity the piece will live in [S].
  - MDF and laser-grade ply are more stable than solid wood [S].
  - Reports on basswood conflict [S].
  - Hold sheets flat while cutting with pins or magnets [S].
- Assemble back to front, removing masking only once everything is aligned [S].

### 3.5 Cut order and LightBurn production
- Cut **inner details first and the outer perimeter last** so the part stays in the sheet [S]. LightBurn's "Cut inner shapes first" does this, but **only when the outer shape is closed**, and grouping or "Reduce travel moves" can defeat it [S].
- **Duplicate overlapping lines double-cut and are a fire hazard** [S]. The exporter must de-duplicate.
- LightBurn tabs are generated per closed shape [S].
- Deepnest and SVGnest (MIT) merge shared lines and nest parts with kerf spacing. Nesting several small layers onto one sheet is a real need [S].

### 3.6 Materials
| Material | Thickness | Notes |
|---|---|---|
| Laser plywood (birch/poplar/basswood) | 3 mm most common | stability varies; "laser grade" preferred [S] |
| MDF | 3 mm | flat, paints well, needs good extraction [S] |
| Cardstock | ~0.3 mm (216–300 gsm) | solid-core tears less [S]; foam/card spacers |
| Acrylic | 3 mm | backlit / edge-lit; mixing with wood common |
| **Never laser**: foam-core/polystyrene, PVC | — | toxic / fire [S] |

---

## 4. LightBurn SVG import — what the generator must emit

| Fact | Status |
|---|---|
| LightBurn maps **colour → layer** by best (nearest) match. Exact palette colours are safest | [C] |
| Import largely ignores fill/stroke *styling* and reads colours. Where both exist, **stroke colour wins**. Line width is ignored | [S] (secondhand staff quote, conflicting threads) |
| Gradients, patterns and embedded rasters are ignored | [S] |
| Layer palette is hard-coded and can't be changed | [S] |
| Palette (verified rows): **00 #000000, 01 #0000FF, 02 #FF0000, 03 #00E000, 04 #D0D000**. T1 #F36926, T2 #0C96D9 (forum) | [S] |
| Layers 05–28: values exist in the official table but I couldn't retrieve them. **Get them from LightBurn's palette export (.ase/.xml) before coding** | [V] |
| Saved project or library settings can override expected layer settings | [S] |
| Size problems come from unitless/px/% width & height, or a viewBox that doesn't match the size. Inkscape assumes 96 DPI, Illustrator 72 DPI | [C] |
| Fill mode needs closed shapes | [S] |
| `.lbrn2` is XML. No official schema, but community docs exist (Kerfview, OpenBurn): `CutSetting` entries indexed by `CutIndex`, `Shape` with `XForm` + `VertList`/`PrimList` | [S] |

**Derived SVG export contract [D]:**
1. `width="…mm" height="…mm"` plus `viewBox="0 0 W H"` with **1 user unit = 1 mm**. No % or px.
2. Only `<path>` elements with absolute coordinates. No `transform`, `<use>`, `<clipPath>`, `<mask>`, `<text>`, CSS classes or `<style>` blocks. Inline attributes only.
3. `fill="none"` and `stroke="<exact LightBurn hex>"` on every path. Operation is encoded by colour: cut, score, engrave-fill and guide each get a dedicated palette slot.
4. Every cut path closed (`Z`). No duplicate or overlapping segments.
5. Group per operation with `<g id="cut">` and so on. Grouping is for humans, since LightBurn keys on colour.
6. Engraved text converted to outlines (paths), never `<text>`.
7. Optional future target: native `.lbrn2`, which carries power and speed per layer. Not for v1, since the format is unofficial.

---

## 5. Existing tools (competitive landscape)

| Tool | What it does | Gap we can fill |
|---|---|---|
| Atomm Layered Cutting / Papercut / Mandala generators | AI: photo/prompt → layered SVG. Adds island bridges. 1:1 mm SVG | Closed SaaS, little DFM control, no hidden-bridge optimisation |
| MarcAM AI Layered Art Studio | prompt/photo → 3/5/7 layers, "starting point, review before cutting" | Output needs manual cleanup |
| LaserBurn AI | Gemini art → traced SVG, "every trace needs cleanup" | Same |
| Depth2Beam | photo → height map → relief / layered SVG export | Relief-oriented |
| TopoStack, topo-layers (OSS), Maperivo, MyLaserTools | DEM → contour layers, cleanup (smoothing, min feature), one SVG per layer + overlay | Maps only |
| Deepnest / SVGnest | nesting | Not a design tool |

**Takeaway [D]:** the common complaint is that output "needs cleanup before
it will cut". The differentiator is **guaranteed-manufacturable output**: DFM
rules enforced by construction, a checklist report, hidden bridges, nesting
and LightBurn-exact export. Generation quality matters, but trustworthiness
of the files matters more to someone feeding a laser.

---

## 6. Algorithms and libraries

| Need | Option | Notes |
|---|---|---|
| Monocular depth from photo | **Depth Anything V2 Small**, ONNX via Transformers.js, WebGPU + WASM fallback | Small = Apache-2.0. **Base/Large = CC-BY-NC**, so avoid them for commercial use [S] |
| Raster → vector | ~~Potrace~~ (**GPL-2.0 in every JS/WASM port**, so it would make the app GPL) / VTracer (MIT, colour, O(n)) | *Round 1: dropped tracing. Use marching squares on continuous fields, and generate procedural content as vectors directly* |
| Polygon booleans and offsets | **Clipper2** (C++). JS: clipper2-wasm (fastest), clipper2-ts. Python: pyclipr | union, difference, inflate/deflate, simplify [S] |
| Min-feature cleanup | Morphological **opening** (deflate then inflate by r) removes features narrower than 2r. **Closing** (inflate then deflate) fills gaps narrower than 2r | standard [D] |
| Nesting | SVGnest/Deepnest (no-fit polygon + GA, MIT) | [S] |
| Depth layering | Quantise depth into N bands. Plane quantisation handles slopes poorly unless there are many planes [S]. Layered-depth-image research (Shih et al. 2020) handles occlusion and inpainting [S] | |
| 3D preview | three.js extrude of each layer polygon at z = i×(t+gap) | [D] |

### 6.1 Core geometric model [D]
Number the layers from the **back**, i = 0 … N−1, and let `h(x,y)` be a
"nearness" field (depth map, label map or procedural height). Then:

- **Glued stack:** `M_i = { h ≥ τ_i }`. This gives **monotone nesting**, M_{N−1} ⊆ … ⊆ M_0, which guarantees every upper piece sits on material below.
- **Spaced shadow box:** `M_i = Frame ∪ { h ≥ τ_i } ∪ Hidden_i`, where the visible part is the same nested set. `Hidden_i` is any material in the region covered by the union of the layers in front. That region is free for bridges and strength.
- **Visible region of layer i:** `V_i = M_i \ ∪_{j>i} M_j`. The occlusion check flags any intended detail that falls outside V_i.
- **Reveal check:** the width of `M_i \ M_{i+1}` along each edge should be at least `min_reveal`.

The whole pipeline is "make a nearness field → pick thresholds → clean each
mask under DFM rules while keeping the nesting → handle islands per
construction mode → vectorise → export". It is the same for photos, maps,
mandalas and procedural landscapes, which is what makes one app able to
cover all of them.

---

## Sources
- [Opt Lasers — layered wood art guide](https://optlasers.com/layered-laser-cut-wood-art-guide)
- [Handyloom — layering tips](https://handyloom.com/techniques-of-laser-cut-artwork/)
- [Craftgineer — stacked layer art](https://craftgineer.com/blog/stacked-layer-art)
- [Crafteker — layered wood wall art](https://crafteker.com/layered-wood-wall-art-laser/)
- [Instructables — layered cut wood landscape](https://www.instructables.com/Create-a-Layered-Cut-Wood-Landscape/)
- [Adafruit — layered LED art panel (WLED)](https://learn.adafruit.com/laser-cut-layered-led-art-panel-wood-acrylic-with-wled/laser-cutting)
- [Loklik — mastering multi-layer paper projects](https://community.loklik.com/t/article-series-mastering-multi-layer-paper-projects-part-3/75468)
- [Orange_Witch — 24 secrets of shadow box](https://note.com/orange_witch/n/n9a8a7ca40787?hl=en)
- [Creative Fabrica — shadow box template designer notes](https://www.creativefabrica.com/the-artistry/3d-crafting/making-a-shadow-box-template-designer-notes/)
- [MuralMoods — colour theory for layered paper art](https://muralmoodsart.com/articles/color-theory-layered-paper-art-guide/)
- [MuralMoods — shadow box with Cricut/Silhouette](https://muralmoodsart.com/articles/how-to-make-layered-paper-cut-shadow-box-cricut-silhouette/)
- [LibreTexts — atmospheric perspective](https://human.libretexts.org/Courses/Coalinga_College/Drawing_Perspectives/05:_Atmospheric_Perspective/5.04:_Understanding_Atmospheric_Perspective)
- [Maperivo — layered SVG best practices](https://maperivo.com/blog/layered-svg-files-for-laser-cutting-best-practices)
- [Maperivo — glue, alignment, kerf, warping](https://maperivo.com/blog/layered-laser-art-glue-alignment-kerf-warping)
- [Supergraphics — 17-layer topographic map case study](https://supergraphics.com/blog/wooden-topographic-map-case-study/)
- [Canadian Woodworking — contour line wall art](https://canadianwoodworking.com/project/contour-line-wall-art/)
- [Glowforge community — papercut lightbox](https://community.glowforge.com/t/papercut-lightbox-and-frame/39080)
- [Atomm — LED sign designs (diffusion)](https://www.atomm.com/collection/11752-led-sign-designs)
- [DigiKey — LED diffusion ideas](https://www.digikey.com/es/maker/projects/13-ideas-for-led-diffusion/9f884021663b43a2b2df33ca334b2bcf)
- [Rockler — layered stain effects](https://rockler.com/learn/layered-color-special-effects-stain)
- [Rothko & Frost — wood dyeing](https://rothkoandfrost.com/blogs/stuff-you-should-know/how-to-dye-wood-a-professional-guide-to-vibrant-deep-grained-finishes)
- [Xometry — laser cutting design rules](https://www.xometry.com/resources/sheet/laser-cutting-rules/)
- [Sculpteo — laser cutting materials guidelines (PDF)](https://info.sculpteo.com/hubfs/Material%20comparisons/Laser%20cutting%20materials%20design%20guidelines.pdf)
- [LightBurn docs — Layer Colors](https://docs.lightburnsoftware.com/LayerColors.html)
- [LightBurn docs — Color Palette](https://docs.lightburnsoftware.com/latest/Reference/UI/ColorPalette/)
- [LightBurn docs — Optimization Settings](https://docs.lightburnsoftware.com/OptimizationSettings.html)
- [LightBurn forum — programmatically creating recognizable SVG](https://forum.lightburnsoftware.com/t/programmaticaly-creating-recognizable-svg-files/184165)
- [LightBurn forum — fill colour into stroke colour](https://forum.lightburnsoftware.com/t/lightburn-turns-fill-color-into-stroke-color-in-svg/115843)
- [LightBurn forum — Inkscape colours wrong](https://forum.lightburnsoftware.com/t/lightburn-importing-colors-all-wrong-from-inkscape/93560)
- [LightBurn forum — LBRN2 file documentation](https://forum.lightburnsoftware.com/t/lbrn2-file-documentation/52174)
- [LightBurn forum — RGB for T1/T2](https://forum.lightburnsoftware.com/t/rgb-values-for-t1-and-t2-layers/60580)
- [vectosolve — LightBurn SVG import guide](https://vectosolve.com/blog/lightburn-svg-import-guide)
- [Dallas Makerspace — LightBurn scaling](https://talk.dallasmakerspace.org/t/lightburn-scaling/35689)
- [Kerfview — .lbrn2 viewer/format](https://kerfview.com/)
- [OpenBurn (GitHub)](https://github.com/SJLS27/openburn)
- [Atomm — layered papercut generator](https://www.atomm.com/creativetools/community/image-to-layered-papercut-generator)
- [MarcAM — AI layered art](https://www.marcam.uk/layered-art.html)
- [LaserBurn AI](https://www.laserburnai.com/)
- [Depth2Beam](https://www.depth2beam.com/)
- [TopoStack](https://topostack.app/)
- [topo-layers (GitHub)](https://github.com/paperclipmonkey/topo-layers)
- [Deepnest (GitHub)](https://github.com/rdwh/deepnest)
- [Depth Anything V2 Small (ONNX)](https://huggingface.co/onnx-community/depth-anything-v2-small)
- [Potrace manual](https://potrace.sourceforge.net/potrace.1.html)
- [Clipper2-ts](https://cdn.jsdelivr.net/npm/clipper2-ts@2.0.1-17/README.md)
- [clipper2-wasm](https://cdn.jsdelivr.net/npm/clipper2-wasm@0.2.1/README.md)
- [Shih et al. 2020 — 3D Photography using Context-aware Layered Depth Inpainting](https://openaccess.thecvf.com/content_CVPR_2020/html/Shih_3D_Photography_Using_Context-Aware_Layered_Depth_Inpainting_CVPR_2020_paper.html)
- [Bak et al. CVPRW 2023 — Variable LDI](https://openaccess.thecvf.com/content/CVPR2023W/LFNAT/papers/Bak_Light_Field_Synthesis_From_a_Monocular_Image_Using_Variable_LDI_CVPRW_2023_paper.pdf)
