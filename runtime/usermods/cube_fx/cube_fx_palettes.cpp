#include "wled.h"
#include "cube_fx_common.h"

// ===========================================================================
// cube_fx_palettes.cpp - audio-reactive palettes, registered at runtime
// ===========================================================================
// These are PALETTES, not effects. They appear in the normal palette dropdown
// and work under any effect - this folder's and WLED's stock ones alike -
// because every effect ultimately asks the segment for a colour and the
// segment reads whichever palette is selected.
//
// No core file is touched. WLED carries a registry for exactly this:
//
//   std::vector<UsermodPalette> usermodPalettes;   // wled00/colors.h
//
// A usermod pushes {palette, name, index, displayName} into it and the entry
// shows up in the UI as "name: displayName". IDs run downward from 255, and
// there are 55 slots; the audioreactive usermod claims three when its "add
// palettes" setting is on, which leaves plenty.
//
// The part that makes them REACTIVE rather than merely custom: Segment::
// loadPalette() reads usermodPalettes[i].palette live, every frame. So a
// usermod that rewrites those sixteen stops in its loop() is repainting the
// palette under whatever is drawing, continuously, with no cooperation needed
// from the effect. That is the whole mechanism.
//
// ---------------------------------------------------------------------------
// THE COLOURS ARE YOURS, NOT MINE
// ---------------------------------------------------------------------------
// None of these hold a view on colour. Each SAMPLES a source palette, and the
// audio decides only where, and how widely, it samples:
//
//   Kick    a narrow window that jumps to a new place in the source on a beat
//   Tilt    a two-tap SPLIT - bass pulls one tap back, treble pushes the other
//           forward, and the spectral balance decides which is heard
//   Bloom   the window WIDENS with loudness, from one colour to the whole ramp
//   Ladder  stop i is source position i, brightness is band i's level
//   Arc     every musical feature at once, each owning a bounded slice of
//           palette travel - see below
//   Sweep   the source, unchanged in brightness, rotated one stop per KICK -
//           sixteen kicks bring it back round. Hue only; see below
//
// The source is set in Usermods settings ("source"), and it is an ordinary WLED
// palette id:
//
//   2..5      WLED's own "primary colour", "primary + secondary" and so on, so
//             these follow the segment's COLOUR PICKERS - pick colours directly
//   0..71     any built-in palette
//   72..200   custom palettes, i.e. any gradient uploaded to the device
//
// Usermod ids (201-255) are refused, because a usermod palette sourcing another
// usermod palette is a loop, and sourcing itself is a loop that also stops
// producing any colour at all after one frame.
//
// ---------------------------------------------------------------------------
// THE TWO-TAP SPLIT
// ---------------------------------------------------------------------------
// Sampling the source at ONE place can only slide. Sampling it at two - one
// pulled back by the bass, one pushed forward by the treble, blended by which
// band is louder - lets the palette come APART on full-spectrum material and
// collapse back to a point when the spectrum narrows. It is the difference
// between a gradient that moves and one that breathes, and it costs one extra
// lookup.
//
// The blend needs a floor. high/(bass+high) is meaningless when both are tiny
// and jitters hard just above silence, so below a small total the two taps are
// simply given equal weight.
//
// ---------------------------------------------------------------------------
// ARC, AND THE SHIFT BUDGET
// ---------------------------------------------------------------------------
// Arc is the one that uses everything. Six musical features each own a bounded
// slice of palette travel and their shifts sum:
//
//   spectral tilt   +/- 80   which way the spectrum leans
//   tempo phase     +/- 12..48, scaled by CONFIDENCE and by energy
//   beat pulse       +  26   a 220 ms envelope on each predicted beat
//   drop intensity   +  42   the tail of a drop
//   build            -  24   NEGATIVE, on purpose
//   sustained surge  +  18   a held bass note
//
// Two of those are worth spelling out. The tempo term uses the PREDICTED phase
// rather than hits, so the palette sways continuously between beats instead of
// only twitching on them - and multiplying by confidence means it fades itself
// out when the lock is poor rather than swaying to a tempo that is not there.
//
// And build is negative while drop is positive: through a riser the palette
// winds steadily backward, and the drop snaps it forward past where it began.
// That is an arc measured in bars rather than in frames, and it is the only
// thing here that operates on a musical timescale longer than a beat.
//
// ---------------------------------------------------------------------------
// SWEEP
// ---------------------------------------------------------------------------
// The whole source, all sixteen stops at full brightness, rotated by one stop
// on every kick. Sixteen kicks is one full turn, so on a 4/4 bar the palette
// comes back round every four bars. Nothing else moves it: no loudness, no
// tempo prediction, no build or drop - a kick, and only a kick, and the same
// amount every time. Brightness is untouched; this is a hue rotation and
// nothing more, which is the point of it.
//
// The step is delivered as a slew rather than a snap - the debt is paid off at
// about a third a frame, the same way the effects deliver a beat - so the
// colours are seen to SWEEP through one stop over ~140 ms rather than cut to
// the next. Silence holds the palette where it got to; the pass-through does
// not reset it.
//
// ---------------------------------------------------------------------------
// CALLING THE SHARED ANALYSERS FROM A USERMOD IS SAFE, BUT NOT OBVIOUSLY SO
// ---------------------------------------------------------------------------
// cfx_tempo() and cfx_drop() sit on fx_lowBeat(), which is a ONE-SHOT: it
// consumes the rising edge of samplePeak so that one hit fires one response.
// Something calling it from outside the render path could therefore eat beats
// that the effects were meant to see. It does not, for opposite reasons on the
// two hosts, and both are worth recording:
//
//   device     strip.now is assigned inside WS2812FX::service(), and
//              UsermodManager::loop() runs BEFORE service() in the main loop.
//              So a usermod sees the PREVIOUS frame's strip.now, hits the
//              one-answer-per-frame guard, and is handed the cached value
//              without consuming anything. Its audio is one frame stale.
//
//   simulator  usermods run first WITH the frame's own strip.now, so the
//              usermod computes and caches, and the effect reads that same
//              cached answer a moment later.
//
// Either way exactly one evaluation happens per frame and nothing is lost.
//
// ---------------------------------------------------------------------------
// THE SIMULATOR RUNS THESE TOO
// ---------------------------------------------------------------------------
// The filename has no NN prefix, so studio/build.py's effect glob skips it -
// it is not an effect - and build.py names it explicitly instead. The simulator
// carries WLED's real palette set, its own usermodPalettes registry and a
// usermod loop, so these appear in its palette list and react there exactly as
// they do on the device.
// ===========================================================================

#ifndef CFX_PAL_COUNT
  #define CFX_PAL_COUNT 6
#endif
#ifndef CFX_PAL_SOURCE_DEFAULT
  #define CFX_PAL_SOURCE_DEFAULT 11    // Rainbow: wide, so the movement shows
#endif
#define CFX_TONE_FLOOR 24              // below this, the split blends evenly

// One shared name pointer for all of them, which is also how
// removeUsermodPalettes() identifies them - it matches on pointer identity,
// not on string contents.
static const char _cfxPalName[] PROGMEM = "CubeFX";
static const char _cfxPal0[]    PROGMEM = "Kick";
static const char _cfxPal1[]    PROGMEM = "Tilt";
static const char _cfxPal2[]    PROGMEM = "Bloom";
static const char _cfxPal3[]    PROGMEM = "Ladder";
static const char _cfxPal4[]    PROGMEM = "Arc";
static const char _cfxPal5[]    PROGMEM = "Sweep";
static const char _cfxSrcKey[]  PROGMEM = "source";

class CfxPalettes : public Usermod {
  private:
    bool     registered = false;
    uint8_t  source     = CFX_PAL_SOURCE_DEFAULT;
    uint8_t  builtFor   = 0xFF;          // which source `src` currently holds
    uint32_t builtCols[3] = {0, 0, 0};
    CRGBPalette16 src;                   // the colours everything is drawn from

    uint8_t  kickPos    = 0;             // where in the source Kick is sitting
    uint8_t  kickEnv    = 0;
    uint8_t  pulse      = 0;             // beat envelope, ~220 ms
    uint8_t  tilt       = 128;           // smoothed bass/treble balance
    uint8_t  loud       = 0;
    uint8_t  bass = 0, treb = 0;
    uint16_t sweepPos = 0;               // Sweep's rotation, in 1/16ths of a stop
    uint16_t sweepOwed = 0;              // rotation owed to it, same units
    uint32_t lastMs     = 0;
    CfxTempoState tempo = {0, 0, 0, 0, 0, 0};
    CfxDropState  drop  = {0, 0, 0, 0, 256, false};

    static um_data_t *audio() {
      um_data_t *um = nullptr;
      if (!UsermodManager::getUMData(&um, USERMOD_ID_AUDIOREACTIVE)) return nullptr;
      return um;
    }

    static const uint32_t *segColors() {
      return strip.getSegment(strip.getMainSegmentId()).colors;
    }

    // Segment::loadPalette() is protected, so it cannot be borrowed - but every
    // table it reads is a public global, so the part that matters is short. A
    // bad or circular id falls back to the default rather than being clamped,
    // so a mistake is visible instead of silently sourcing itself.
    void buildSource() {
      const uint32_t *cols = segColors();
      uint8_t pal = source;
      if (pal > WLED_CUSTOM_PALETTE_ID_BASE) pal = CFX_PAL_SOURCE_DEFAULT;
      if (pal >= FIXED_PALETTE_COUNT &&
          (WLED_CUSTOM_PALETTE_ID_BASE - pal) >= (int)customPalettes.size())
        pal = CFX_PAL_SOURCE_DEFAULT;

      const CRGB p0 = CRGB(R(cols[0]), G(cols[0]), B(cols[0]));
      const CRGB p1 = CRGB(R(cols[1]), G(cols[1]), B(cols[1]));
      const CRGB p2 = CRGB(R(cols[2]), G(cols[2]), B(cols[2]));
      switch (pal) {
        case 0: case 1: src = PartyColors_gc22; break;
        case 2:  src = CRGBPalette16(p0); break;
        case 3:  src = CRGBPalette16(p0, p0, p1, p1); break;
        case 4:  src = CRGBPalette16(p2, p1, p0); break;
        case 5:
          if (cols[2]) src = CRGBPalette16(p0,p0,p0,p0,p0,p1,p1,p1,p1,p1,p2,p2,p2,p2,p2,p0);
          else         src = CRGBPalette16(p0,p0,p0,p0,p0,p0,p0,p0,p1,p1,p1,p1,p1,p1,p1,p1);
          break;
        default:
          if (pal >= FIXED_PALETTE_COUNT) {
            src = customPalettes[WLED_CUSTOM_PALETTE_ID_BASE - pal];
          } else if (pal < DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT) {
            src = *fastledPalettes[pal - DYNAMIC_PALETTE_COUNT];
          } else {
            // pgm_read_ptr, not pgm_read_dword. The firmware's own copy of
            // this uses the dword form, which is right where a pointer is 32
            // bits and truncates one where it is 64 - the simulator builds for
            // a 64-bit host and would dereference a cut-down pointer. The ptr
            // form is correct on both.
            byte tcp[72];
            memcpy_P(tcp, (const byte *)pgm_read_ptr(&(gGradientPalettes[pal - (DYNAMIC_PALETTE_COUNT + FASTLED_PALETTE_COUNT)])), sizeof(tcp));
            src.loadDynamicGradientPalette(tcp);
          }
          break;
      }
      builtFor = source;
      builtCols[0] = cols[0]; builtCols[1] = cols[1]; builtCols[2] = cols[2];
    }

    // One colour out of the source, scaled. Everything is built from this and
    // nothing else, which is what keeps these on the chosen colours.
    inline CRGB pick(uint8_t pos, uint8_t bri) const {
      const uint32_t c = ColorFromPalette(src, pos, bri, LINEARBLEND);
      return CRGB(R(c), G(c), B(c));
    }

    // The two-tap split: bass pulls one tap back, treble pushes the other
    // forward, blended by which band is carrying. See the header.
    inline CRGB pick2(int pos, uint8_t bri, uint8_t spread) const {
      const uint8_t lo = (uint8_t)(pos - (int)scale8(bass, spread));
      const uint8_t hi = (uint8_t)(pos + (int)scale8(treb, spread));
      const int total = (int)bass + (int)treb;
      const uint8_t mix = (total >= CFX_TONE_FLOOR)
                        ? (uint8_t)(((int)treb * 255) / total) : 128;
      const CRGB a = pick(lo, bri), b = pick(hi, bri);
      return CRGB((uint8_t)(((int)a.r * (255 - mix) + (int)b.r * mix) >> 8),
                  (uint8_t)(((int)a.g * (255 - mix) + (int)b.g * mix) >> 8),
                  (uint8_t)(((int)a.b * (255 - mix) + (int)b.b * mix) >> 8));
    }

    // Silence leaves the source ALONE rather than showing a dimmed or drifting
    // version of it. Picking one of these with nothing playing should look like
    // the palette it is built from, not like a broken palette.
    void passThrough() {
      for (auto &p : usermodPalettes) {
        if (p.name != _cfxPalName) continue;
        // i*16, not i*17: ColorFromPalette takes the entry from pos>>4 and
        // blends by the low nibble, so i*16 lands exactly ON entry i and
        // reproduces the source stop for stop. i*17 walks a sixteenth of an
        // entry further each step and skews the whole ramp.
        //
        // Sweep keeps its rotation through silence - it is where the kicks
        // left it, and it should still be there when they come back.
        const uint8_t off = (p.palIndex == 5) ? (uint8_t)(sweepPos >> 4) : 0;
        for (int i = 0; i < 16; i++) p.palette.entries[i] = pick((uint8_t)(i * 16 + off), 255);
      }
    }

  public:
    void setup() override {
      static const char *const names[CFX_PAL_COUNT] PROGMEM =
        { _cfxPal0, _cfxPal1, _cfxPal2, _cfxPal3, _cfxPal4, _cfxPal5 };
      for (int i = 0; i < CFX_PAL_COUNT; i++) {
        if (usermodPalettes.size() >= WLED_MAX_USERMOD_PALETTES) break;
        usermodPalettes.push_back({ CRGBPalette16(CRGB::Black), _cfxPalName,
                                    (uint8_t)i, names[i] });
        registered = true;
      }
      buildSource();
    }

    void loop() override {
      if (!registered) return;
      um_data_t *um = audio();
      if (!um) return;

      // strip.now, NOT millis(). WLED sets strip.now = millis() every service,
      // so on the device they are the same number - but the simulator advances
      // a SIMULATED clock and renders far faster than real time, so gating on
      // wall time meant dt never cleared the threshold and these palettes sat
      // frozen on their first frame. The effect clock is the one to trust.
      const uint32_t now = strip.now;
      uint16_t dt = (uint16_t)(now - lastMs);
      if (dt < 20) return;                   // 50 Hz is plenty for a gradient
      if (dt > 250) dt = 250;
      lastMs = now;

      // Rebuilt when the setting moves, and also when the segment's COLOURS
      // move - sources 2-5 are built from them, so a colour picker has to take
      // effect without a restart.
      {
        const uint32_t *c = segColors();
        if (source != builtFor || c[0] != builtCols[0] ||
            c[1] != builtCols[1] || c[2] != builtCols[2]) buildSource();
      }

      const float   vol  = *(float *)um->u_data[0];
      const uint8_t *fft = (uint8_t *)um->u_data[2];
      int b = 0, m = 0, t = 0;
      cfx_bands(fft, b, m, t);
      bass = (uint8_t)b; treb = (uint8_t)t;

      // See the header: this is a cached read, not a fresh consume, so the
      // effects keep every beat.
      tempo = cfx_tempo(um);
      drop  = cfx_drop(um, tempo);

      const uint8_t energy = (bass > treb) ? bass : treb;
      if (!energy) { passThrough(); return; }

      // --- beat envelope --------------------------------------------------
      // Driven by the PREDICTED beat, so it still lands when a hit is missed,
      // and takes the hit's strength when there was one.
      {
        const int d = (int)pulse - ((int)dt * 255) / 220;
        pulse = (uint8_t)(d < 0 ? 0 : d);
        if (tempo.beat) {
          const uint8_t s = tempo.hit ? tempo.hit : 160;
          if (s > pulse) pulse = s;
        }
      }

      // --- Sweep's step ---------------------------------------------------
      // One stop per KICK - tempo.hit is the actual low-band hit this frame,
      // not the predicted beat, so a bar with no kick in it does not turn the
      // palette. Owed and paid at a third a frame: 16 positions per stop, in
      // sixteenths so the slew has something to divide.
      if (tempo.hit) sweepOwed = (uint16_t)(sweepOwed + 256u);   // 16 positions
      if (sweepOwed) {
        uint32_t give = ((uint32_t)sweepOwed * dt) / 70u;
        if (!give) give = 1;
        if (give > sweepOwed) give = sweepOwed;
        sweepPos  = (uint16_t)(sweepPos + give);
        sweepOwed = (uint16_t)(sweepOwed - give);
      }

      // --- Kick's own step ------------------------------------------------
      {
        if (tempo.beat && bass > 40) {
          // Step to somewhere that is actually LIT. Kick samples a narrow
          // slice, and plenty of palettes have a long dark end - Fire is a
          // quarter black - so a blind jump lands there often enough that the
          // beat reads as the effect dying rather than as a hit. Up to four
          // steps looking for a live spot, then take what there is: a source
          // that is dark everywhere should stay dark, not be forced bright.
          for (int k = 0; k < 4; k++) {
            kickPos = (uint8_t)(kickPos + 71);
            const CRGB c = pick(kickPos, 255);
            if ((int)c.r + (int)c.g + (int)c.b > 90) break;
          }
          kickEnv = 255;
        }
        const int d = (int)kickEnv - ((int)dt * 255) / 420;
        kickEnv = (uint8_t)(d < 0 ? 0 : d);
      }

      // --- smoothed balance and loudness ----------------------------------
      {
        const int denom = (int)bass + (int)treb + 1;
        const int want  = 128 + (((int)treb - (int)bass) * 127) / denom;
        tilt = (uint8_t)(tilt + ((want - (int)tilt) * (int)dt) / 260);
        int lw = (int)(vol * 2.2f); if (lw > 255) lw = 255;
        loud = (uint8_t)((lw > (int)loud) ? lw
                         : (int)loud - (((int)loud - lw) * (int)dt) / 500);
      }

      // --- Arc's shift budget ---------------------------------------------
      int arcShift;
      {
        const int spectral = (((int)tilt - 128) * 80) / 128;
        const int span     = 12 + (int)scale8(energy, 36);
        const int phase    = ((((int)tempo.phase - 128) * span) * (int)tempo.confidence)
                             / (128 * 255);
        const int pulseS   = ((int)pulse * 26) / 255;
        const int dropS    = ((int)drop.intensity * 42) / 255;
        const int buildS   = -(((int)drop.build * 24) / 255);
        const int surgeS   = ((int)drop.surge * 18) / 255;
        arcShift = spectral + phase + pulseS + dropS + buildS + surgeS;
      }

      for (auto &p : usermodPalettes) {
        if (p.name != _cfxPalName) continue;
        CRGB *e = p.palette.entries;
        switch (p.palIndex) {

          case 0: {   // Kick - a narrow slice of the source, moving on the beat
            const uint8_t lift = (uint8_t)(70 + (kickEnv * 185) / 255);
            for (int i = 0; i < 16; i++) {
              const uint8_t pos = (uint8_t)(kickPos + (i - 8) * 3);
              uint8_t v = (uint8_t)((i == 0) ? 0 : lift);   // keep a black stop
              if (i > 12) v = (uint8_t)(v / (i - 11));      // and fall away
              e[i] = pick(pos, v);
            }
            break; }

          case 1: {   // Tilt - the two-tap split
            for (int i = 0; i < 16; i++)
              e[i] = pick2(i * 6, (uint8_t)(i == 0 ? 0 : 45 + i * 14), 64);
            break; }

          case 2: {   // Bloom - loudness WIDENS the slice, it does not brighten it
            // Quiet is one colour held dim; loud opens out across the whole
            // source at full contrast. Stop 0 stays black either way, so it
            // never becomes a wash.
            const int span = 12 + ((int)loud * 243) / 255;
            for (int i = 0; i < 16; i++) {
              const uint8_t pos = (uint8_t)((int)loud + (i * span) / 15);
              int v = 30 + (i * (40 + ((int)loud * 185) / 255)) / 15;
              if (v > 255) v = 255;
              e[i] = pick(pos, (uint8_t)(i == 0 ? 0 : v));
            }
            break; }

          case 3: {   // Ladder - the spectrum ACROSS the stops
            // Stop i is band i, at source position i, so a gradient sweep walks
            // up the spectrum: the palette's SHAPE is the sound while its
            // colours stay the ones that were chosen.
            for (int i = 0; i < 16; i++) e[i] = pick((uint8_t)(i * 16), fft[i]);
            break; }

          case 5: {   // Sweep - the source, rotated. Hue only, full brightness.
            const uint8_t off = (uint8_t)(sweepPos >> 4);
            for (int i = 0; i < 16; i++) e[i] = pick((uint8_t)(i * 16 + off), 255);
            break; }

          default: {  // Arc - the whole budget, through the split
            // Brightness leans on the beat envelope and the drop tail, so the
            // palette gains contrast as a section arrives rather than simply
            // getting brighter. Stop 0 stays black.
            const int lift = 150 + ((int)pulse * 60) / 255
                                 + ((int)drop.intensity * 45) / 255;
            for (int i = 0; i < 16; i++) {
              int v = (i == 0) ? 0 : (40 + (i * lift) / 15);
              if (v > 255) v = 255;
              e[i] = pick2(arcShift + i * 15, (uint8_t)v, 48);
            }
            break; }
        }
      }
    }

    void addToConfig(JsonObject &root) override {
      JsonObject top = root.createNestedObject(FPSTR(_cfxPalName));
      top[FPSTR(_cfxSrcKey)] = source;
    }

    bool readFromConfig(JsonObject &root) override {
      JsonObject top = root[FPSTR(_cfxPalName)];
      if (top.isNull()) return false;
      const bool ok = getJsonValue(top[FPSTR(_cfxSrcKey)], source);
      builtFor = 0xFF;                       // force a rebuild on the next loop
      return ok;
    }

    // `source` is a palette id, so it gets the palette DROPDOWN rather than a
    // number field - nobody should have to know that Aurora is 50. The list is
    // built from JSON_palette_names, the same table the main UI reads, so the
    // names here are the names there and a palette added to the firmware turns
    // up in this list without anything being edited.
    //
    // The options are emitted ONCE as a JS array and then looped into the
    // select. Seventy-odd addOption() calls printed straight out is a few KB of
    // script, and the whole usermod settings block is wrapped in one function
    // that has to parse as a unit - the bank usermod on this same page already
    // learned that the hard way, and a script truncated mid-call silently
    // leaves every field as the raw number input it started as. The array form
    // is about a third the size. CFXPS is named apart from the bank's CFXO and
    // CFXD because they share that one function scope.
    //
    // Custom palettes are appended by id, so uploaded gradients are selectable
    // by their real names too.
    //
    // "* Random Cycle" (id 1) is deliberately absent. It has no meaning as a
    // SOURCE - buildSource() resolves it to Party, same as Default - and
    // listing it would promise a cycle that is not implemented. An old config
    // holding 1 lands on option 0, which behaves identically, so nothing
    // silently changes colour.
    void appendConfigData(Print &s) override {
#ifndef CFX_SIM
      char nm[36];
      s.print(F("var CFXPS=["));
      bool first = true;
      for (unsigned i = 0; i < FIXED_PALETTE_COUNT; i++) {
        if (i == 1) continue;
        extractModeName(i, JSON_palette_names, nm, sizeof(nm) - 1);
        if (!first) s.print(',');
        first = false;
        s.print(F("['")); s.print(nm); s.print(F("',")); s.print((int)i); s.print(']');
      }
      for (unsigned i = 0; i < customPalettes.size(); i++) {
        const unsigned id = WLED_CUSTOM_PALETTE_ID_BASE - i;
        extractModeName(id, JSON_palette_names, nm, sizeof(nm) - 1);
        s.print(F(",['")); s.print(nm); s.print(F("',")); s.print((int)id); s.print(']');
      }
      s.print(F("];var CFXPD=addDropdown('")); s.print(FPSTR(_cfxPalName));
      s.print(F("','")); s.print(FPSTR(_cfxSrcKey));
      s.print(F("');for(var _p=0;_p<CFXPS.length;_p++)"
                "addOption(CFXPD,CFXPS[_p][0],CFXPS[_p][1]);"));
      s.print(F("addInfo('CubeFX:source',1,'<i>Where the CubeFX audio palettes "
                "take their colours from. The starred entries follow this "
                "segment&apos;s colour pickers, so you can choose the colours "
                "directly and they update live.</i>');"));
#endif
    }

    uint16_t getId() override { return USERMOD_ID_UNSPECIFIED; }

    // The device writes `source` through the settings page. A host that has no
    // settings page - the simulator - needs some way in, and a setter is the
    // whole of it.
    void setSource(uint8_t s) { source = s; builtFor = 0xFF; }
    uint8_t getSource() const { return source; }

    // One colour straight out of the source palette, for effects (and the
    // Studio's Palette-source node) that want the chosen colours without the
    // audio behaviour. Builds the source on first use if loop() has not.
    uint32_t sourceColor(uint8_t pos, uint8_t bri) {
      const uint32_t *cols = segColors();
      if (builtFor != source || builtCols[0] != cols[0] || builtCols[1] != cols[1] || builtCols[2] != cols[2])
        buildSource();
      const CRGB c = pick(pos, bri);
      return RGBW32(c.r, c.g, c.b, 0);
    }
};

static CfxPalettes cfx_palettes_instance;
REGISTER_USERMOD(cfx_palettes_instance);

// Free functions so a host can reach the setting without knowing the class.
void    cfxSetPaletteSource(uint8_t s) { cfx_palettes_instance.setSource(s); }
uint8_t cfxGetPaletteSource()          { return cfx_palettes_instance.getSource(); }
uint32_t cfxPaletteSourceColor(uint8_t pos, uint8_t bri) { return cfx_palettes_instance.sourceColor(pos, bri); }
