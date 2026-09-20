#ifndef CFX_WITH_PARAM_MEMORY
#define CFX_WITH_PARAM_MEMORY 1     // per-effect slider memory: the studio's feature picker sets -D CFX_WITH_PARAM_MEMORY=0 to leave it out
#endif
#if CFX_WITH_PARAM_MEMORY
#include "wled.h"
#include <vector>

// ===========================================================================
// cube_fx_param_memory.cpp - per-effect slider memory
// ===========================================================================
// WLED's per-effect "defaults" are baked into each effect's data string and
// never change. This layers a MEMORY on top: whenever the active segment's
// mode changes, it stashes the sliders the outgoing effect was actually left
// on, and if the incoming effect has been visited before, restores ITS
// stashed sliders instead of the hardcoded defaults Segment::setMode() just
// loaded.
//
// Keyed by a hash of the effect's NAME, not its numeric mode ID. IDs shift
// every time an effect is added or removed - which happens constantly while
// cube_fx is still being built out - so an ID-keyed table would quietly
// hand the wrong effect's memory to whatever now sits at that slot. Names
// are what a user actually thinks of as "the effect" and stay stable across
// rebuilds even as the effect LIST keeps changing.
//
// Tracks whichever segment is WLED's "main" segment - the one both the OLED
// menu and the web UI treat as active - not a separate table per segment.
//
// Only speed/intensity/custom1-3/check1-3 are remembered, on purpose: colour
// and palette have their own persistence story (see ace_ui_menu.cpp) and
// mixing the two would make it unclear which system owns what.
// ---------------------------------------------------------------------------

#ifndef CFX_PM_FILE
  #define CFX_PM_FILE "/cfx_pmem.bin"
#endif
#ifndef CFX_PM_SAVE_DEBOUNCE_MS
  #define CFX_PM_SAVE_DEBOUNCE_MS 4000   // coalesce rapid effect-hopping into one flash write
#endif
#ifndef CFX_PM_SETTLE_MS
  #define CFX_PM_SETTLE_MS 1500          // how long the sliders must hold still before we record them
#endif
#ifndef CFX_PM_RESTORE_MS
  #define CFX_PM_RESTORE_MS 600          // how long a pending restore keeps looking for its moment
#endif

// millis() comparisons done as a signed difference so a 49-day rollover cannot
// park a pending write forever.
#define CFX_DUE(t) ((t) && (int32_t)(millis() - (t)) >= 0)

struct CfxParamRec {
  uint32_t nameHash;
  uint8_t  speed, intensity, c1, c2, c3;
  uint8_t  checks;   // bit0=check1, bit1=check2, bit2=check3
};

static std::vector<CfxParamRec> cfxParamMem;
static bool     cfxPmLoaded   = false;
static uint8_t  cfxPmLastMode = 0;
static bool     cfxPmHaveLast = false;
static uint32_t cfxPmDirtyAt  = 0;        // millis() a save is owed by, 0 = nothing pending
static uint32_t cfxPmSettleAt = 0;        // millis() the live sliders count as "stopped moving"
static uint32_t cfxPmRestoreBy = 0;       // a restore is owed until this millis(), 0 = none pending

// Continuously-refreshed copy of "whatever the current effect is showing
// right now" - captured every loop() so that the INSTANT a mode change is
// noticed, we already have a last-known-good snapshot from a moment before
// the switch. By the time a change is detected, Segment::setMode() has
// already overwritten the sliders with the NEW effect's defaults, so reading
// the segment itself at that point would stash the wrong effect's numbers.
static uint8_t cfxShadowSpeed = 0, cfxShadowIntensity = 0;
static uint8_t cfxShadowC1 = 0, cfxShadowC2 = 0, cfxShadowC3 = 0, cfxShadowChecks = 0;

static inline uint8_t cfxPackChecks(const Segment &sg) {
  return (uint8_t)((sg.check1 ? 1 : 0) | (sg.check2 ? 2 : 0) | (sg.check3 ? 4 : 0));
}

static uint32_t cfxNameHash(const char *name) {
  uint32_t h = 2166136261u;   // FNV-1a
  for (;;) {
    const char c = (char)pgm_read_byte(name++);
    if (!c || c == '@') break;
    h ^= (uint8_t)c;
    h *= 16777619u;
  }
  return h;
}

static CfxParamRec *cfxFind(uint32_t hash) {
  for (auto &r : cfxParamMem) if (r.nameHash == hash) return &r;
  return nullptr;
}

static void cfxPmLoad() {
  cfxParamMem.clear();
  File f = WLED_FS.open(CFX_PM_FILE, "r");
  if (!f) return;
  CfxParamRec rec;
  while (f.read((uint8_t *)&rec, sizeof(rec)) == (int)sizeof(rec)) cfxParamMem.push_back(rec);
  f.close();
}

static void cfxPmSaveNow() {
  File f = WLED_FS.open(CFX_PM_FILE, "w");
  if (!f) return;
  for (auto &r : cfxParamMem) f.write((uint8_t *)&r, sizeof(r));
  f.close();
  cfxPmDirtyAt = 0;
}

static void cfxPmMarkDirty() { cfxPmDirtyAt = millis() + CFX_PM_SAVE_DEBOUNCE_MS; }

// Stash the SHADOW (captured a moment ago, while `forMode` was still active)
// under forMode's name hash - never the segment's current live values, which
// by now belong to whatever effect we just switched TO.
static void cfxPmStash(uint8_t forMode) {
  const uint32_t h = cfxNameHash(strip.getModeData(forMode));
  CfxParamRec *r = cfxFind(h);
  // Already holding exactly this? Then there is nothing to write, and saying
  // so here keeps both callers - the mode-change path and the settle timer -
  // from queueing pointless flash writes.
  if (r && r->speed == cfxShadowSpeed && r->intensity == cfxShadowIntensity
        && r->c1 == cfxShadowC1 && r->c2 == cfxShadowC2 && r->c3 == cfxShadowC3
        && r->checks == cfxShadowChecks) return;
  if (!r) { cfxParamMem.push_back(CfxParamRec{}); r = &cfxParamMem.back(); r->nameHash = h; }
  r->speed     = cfxShadowSpeed;
  r->intensity = cfxShadowIntensity;
  r->c1        = cfxShadowC1;
  r->c2        = cfxShadowC2;
  r->c3        = cfxShadowC3;
  r->checks    = cfxShadowChecks;
  cfxPmMarkDirty();
}

static bool cfxPmRestore(Segment &sg, uint8_t forMode) {
  const uint32_t h = cfxNameHash(strip.getModeData(forMode));
  CfxParamRec *r = cfxFind(h);
  if (!r) return false;
  sg.speed     = r->speed;
  sg.intensity = r->intensity;
  sg.custom1   = r->c1;
  sg.custom2   = r->c2;
  sg.custom3   = r->c3 & 0x1F;   // custom3 is a 5-bit field
  sg.check1    = (r->checks & 1) != 0;
  sg.check2    = (r->checks & 2) != 0;
  sg.check3    = (r->checks & 4) != 0;

  // Deliberately NO markForReset() here, and it must stay that way.
  //
  // Every value above is read live, every frame, by the effect - which is
  // exactly why moving a slider in the web UI does not reset the segment
  // either. Resetting was doing something the normal path never does, and it is
  // expensive in a way that is easy to miss: resetIfRequired() FREES the
  // segment buffer outright rather than clearing it whenever the buffer is
  // larger than FAIR_DATA_PER_SEG (about 2 KB), so a big effect had its whole
  // allocation thrown away and had to find that many contiguous bytes again on
  // the very next frame - competing with the JSON buffers of the web request
  // that triggered the restore. On Soap, at ~26 KB, that request loses often
  // enough to raise "error 8 / effect RAM depleted" whenever a control is
  // touched.
  //
  // Nothing needs the reset. Sliders and checkboxes take effect on the next
  // frame regardless, an actual effect CHANGE is reset by WLED anyway, and the
  // one case that really does invalidate cached state - Flat mode flipping the
  // cube/flat geometry - is caught by each effect's own "did my mode change"
  // rebuild test. The geometry watchdog below still resets, because a dimension
  // change genuinely does strand stale coordinate tables.
  return true;
}

// Is the segment sitting on exactly what Segment::setMode(fx, true) would have
// just written? If so, this was a PLAIN effect switch - the web UI and the OLED
// menu both load defaults on every pick - and nobody supplied explicit slider
// values, so our memory is free to take over.
//
// If anything differs, the values were set DELIBERATELY by something else: a
// preset, a playlist, or a JSON API call like {"seg":{"fx":5,"sx":200}}. Those
// have to win, or loading a preset would silently get its sliders replaced by
// whatever the effect was last left on - which is exactly what this check is
// here to prevent. Comparing against the defaults (rather than inspecting
// currentPreset) keeps that true no matter which of those set the values, and
// does not depend on when handlePresets() runs relative to this usermod.
static bool cfxAtDefaults(const Segment &sg, uint8_t fx) {
  int16_t o;
  o = extractModeDefaults(fx, "sx"); if (sg.speed     != ((o >= 0) ? (uint8_t)o : DEFAULT_SPEED))     return false;
  o = extractModeDefaults(fx, "ix"); if (sg.intensity != ((o >= 0) ? (uint8_t)o : DEFAULT_INTENSITY)) return false;
  o = extractModeDefaults(fx, "c1"); if (sg.custom1   != ((o >= 0) ? (uint8_t)o : DEFAULT_C1))        return false;
  o = extractModeDefaults(fx, "c2"); if (sg.custom2   != ((o >= 0) ? (uint8_t)o : DEFAULT_C2))        return false;
  o = extractModeDefaults(fx, "c3"); if (sg.custom3   != ((o >= 0) ? (uint8_t)(o & 0x1F) : DEFAULT_C3)) return false;
  o = extractModeDefaults(fx, "o1"); if (sg.check1    != ((o >= 0) ? (bool)o : false))                return false;
  o = extractModeDefaults(fx, "o2"); if (sg.check2    != ((o >= 0) ? (bool)o : false))                return false;
  o = extractModeDefaults(fx, "o3"); if (sg.check3    != ((o >= 0) ? (bool)o : false))                return false;
  return true;
}

// ---------------------------------------------------------------------------
// Geometry watchdog
// ---------------------------------------------------------------------------
// Toggling mirror / mirror_y halves a segment's virtual width / height, so
// SEG_W and SEG_H change underneath a running effect. Segment::allocateData()
// hands back the EXISTING buffer whenever it is already large enough and does
// not reset `call` when the required size merely SHRINKS, so every cube_fx
// effect carries on reading coordinate LUTs built for the old geometry.
//
// Most effects mask this by accident - their cube/flat flag flips when
// cfx_isCube() stops matching, which forces a rebuild - but the symmetric case
// slips through: 48x48 -> 24x24 with both mirrors on is still square, still
// reads as a cube, and renders through stale LUTs.
//
// The OLED menu resets explicitly when it flips those flags, but json.cpp
// assigns seg.mirror / seg.reverse straight from the payload with no reset at
// all, so the web UI, the HTTP API and presets all still slip through.
// Watching the dimensions here catches every path centrally, without patching
// core. Dimensions are packed w<<16|h; 0 means "not seen yet", so the first
// observation of a segment never triggers a reset.
static std::vector<uint32_t> cfxGeom;

static void cfxGeomWatch() {
  const unsigned nSeg = strip.getSegmentsNum();
  if (cfxGeom.size() != nSeg) cfxGeom.assign(nSeg, 0);
  for (unsigned s = 0; s < nSeg; s++) {
    Segment &sg = strip.getSegment(s);
    const uint32_t dims = ((uint32_t)sg.virtualWidth() << 16) | (uint32_t)sg.virtualHeight();
    if (cfxGeom[s] && cfxGeom[s] != dims) sg.markForReset();
    cfxGeom[s] = dims;
  }
}

static void cfxRefreshShadow(const Segment &sg) {
  cfxShadowSpeed     = sg.speed;
  cfxShadowIntensity = sg.intensity;
  cfxShadowC1        = sg.custom1;
  cfxShadowC2        = sg.custom2;
  cfxShadowC3        = sg.custom3;
  cfxShadowChecks    = cfxPackChecks(sg);
}

// Have the live sliders moved away from the shadow captured last frame?
static bool cfxSlidersMoved(const Segment &sg) {
  return sg.speed    != cfxShadowSpeed || sg.intensity != cfxShadowIntensity
      || sg.custom1  != cfxShadowC1    || sg.custom2   != cfxShadowC2
      || sg.custom3  != cfxShadowC3    || cfxPackChecks(sg) != cfxShadowChecks;
}

class CubeFx_ParamMemoryUsermod : public Usermod {
 public:
  void setup() override {}

  void loop() override {
    if (!cfxPmLoaded) { cfxPmLoad(); cfxPmLoaded = true; }

    cfxGeomWatch();

    Segment &sg = strip.getSegment(strip.getMainSegmentId());
    const uint8_t mode = sg.mode;

    if (!cfxPmHaveLast) {
      // Boot: adopt whatever WLED already restored - the saved state in
      // cfg.json, or the boot preset - instead of overriding it. That state IS
      // where the user left the device, so replacing it with memory would gain
      // nothing and would clobber a boot preset's carefully chosen sliders.
      cfxPmHaveLast = true;
      cfxPmLastMode = mode;
    } else if (mode != cfxPmLastMode) {
      cfxPmStash(cfxPmLastMode);
      cfxPmLastMode  = mode;
      cfxPmRestoreBy = millis() + CFX_PM_RESTORE_MS;   // owed, not yet attempted
    }

    // Keep trying to restore for a short window rather than taking a single shot
    // on the frame the mode change is noticed.
    //
    // That single shot was the bug behind "the web UI loads an effect on its
    // defaults instead of my saved values". The UI does not necessarily deliver
    // the new effect id and its default slider values in the same message, so
    // there is a window where the mode has already changed but the sliders still
    // hold the OUTGOING effect's numbers. cfxAtDefaults() is false for that
    // frame, the restore was skipped - and because cfxPmLastMode had already
    // been updated, it was never reconsidered. The saved values then sat unused
    // until something else happened to read them back.
    //
    // Waiting for the defaults to actually land fixes it without weakening the
    // guard: a preset or an explicit JSON call sets values that are NOT the
    // defaults, so the window simply expires and memory stays out of the way.
    if (cfxPmRestoreBy) {
      if (cfxAtDefaults(sg, mode)) {
        if (cfxPmRestore(sg, mode)) stateUpdated(CALL_MODE_BUTTON);
        cfxPmRestoreBy = 0;                            // taken
      } else if (CFX_DUE(cfxPmRestoreBy)) {
        cfxPmRestoreBy = 0;                            // deliberate values won
      }
    }

    // Record the CURRENT effect once its sliders stop moving, rather than only
    // on the way out of it. Stashing solely on a mode change meant tweaking a
    // dial and then power-cycling - without ever switching effects - lost the
    // tweak, because the table had never learned it.
    //
    // Re-armed on every movement, so a long slow turn of the knob records once
    // at the end instead of once per detent.
    if (cfxSlidersMoved(sg)) {
      cfxPmSettleAt = millis() + CFX_PM_SETTLE_MS;
    } else if (CFX_DUE(cfxPmSettleAt)) {
      cfxPmSettleAt = 0;
      cfxPmStash(mode);       // no-ops if the table already holds these values
    }

    cfxRefreshShadow(sg);   // always ready for the next switch, whenever it comes

    if (CFX_DUE(cfxPmDirtyAt)) cfxPmSaveNow();
  }
};

static CubeFx_ParamMemoryUsermod cube_fx_param_memory;
REGISTER_USERMOD(cube_fx_param_memory);
#endif  // CFX_WITH_PARAM_MEMORY
