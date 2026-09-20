#pragma once

#include "wled.h"

// ===========================================================================
// cube_fx_bank.h - which effects get a slot, and in what order
// ===========================================================================
// WLED effect IDs are one byte and 255 is the "not added" sentinel, so the
// WHOLE DEVICE - built-ins plus every usermod - can hold at most 254 effects.
// With 216 built-ins registered into 220 pre-allocated entries, a usermod gets
// the 4 leftover RSVD gaps plus (255 - 220), which is 39 slots in total. This
// set already uses 34 of them.
//
// Past that ceiling addEffect() returns 255 and the effect SILENTLY does not
// appear - no log, no error. Worse, WHICH effects lose out is decided by the
// order the linker happens to run static initialisers in, which is unspecified
// per translation unit. So the failure is both invisible and non-deterministic:
// "some of my effects are missing and it changes between builds".
//
// The bank fixes both halves of that:
//
//   * You choose which compiled effects claim the slots, so the set can be
//     larger than the ceiling and you pick what ships.
//   * You choose the ORDER, so effect IDs stop depending on link order. Slot
//     order becomes ID order becomes the order they appear in the WLED list and
//     the on-cube menu.
//
// ---------------------------------------------------------------------------
// THE ROSTER AND THE REGISTRY ARE NOT THE SAME LIST
// ---------------------------------------------------------------------------
// This is the whole trick, and getting it wrong makes the feature a one-way
// door. If the bank only ever knew about effects it had registered with WLED,
// then a disabled effect would be invisible to the settings page and could
// never be re-enabled.
//
// So every effect reports itself here whether or not it gets a slot:
// cfxBankAdd() ALWAYS appends to the roster and only CONDITIONALLY calls
// strip.addEffect(). The roster is therefore the complete set of compiled
// effects, and the settings page - which renders on an HTTP request, long after
// every usermod's setup() has run - can offer all of them.
//
// ---------------------------------------------------------------------------
// WHY SLOTS STORE A NAME HASH AND NOT AN INDEX
// ---------------------------------------------------------------------------
// Roster indices depend on link order, so they are exactly as unstable as the
// problem this is here to solve; file-prefix numbers get renumbered whenever
// effects are culled. A hash of the effect's NAME survives both, and it is what
// cube_fx_param_memory.cpp already keys on for the same reason. A slot naming an
// effect that no longer exists in the build reads as empty rather than silently
// pointing at whatever moved into that position.
// ===========================================================================

#ifndef CFX_BANK_SLOTS
  #define CFX_BANK_SLOTS 36        // of ~39 available; the rest is headroom
#endif
#ifndef CFX_BANK_MAX_FX
  #define CFX_BANK_MAX_FX 64       // roster capacity - compiled effects, not slots
#endif

struct CfxBankEntry {
  uint16_t    hash;                // of the display name, see cfxBankHash()
  const char *data;                // the _data_FX_MODE_* metadata string
  void      (*fn)();               // WS2812FX::mode_ptr is private to that class
  bool        placed;              // did it actually get a slot this boot
};

// Roster of every compiled effect, filled during setup() in link order.
inline CfxBankEntry *cfxBankRoster() {
  static CfxBankEntry r[CFX_BANK_MAX_FX];
  return r;
}
inline uint16_t &cfxBankCount() { static uint16_t n = 0; return n; }  // 16-bit: the sim rosters every stock effect too

// The chosen set, in order. 0 = empty slot. Owned by the bank usermod, which
// loads it from config before any effect's setup() runs - WLED reads the config
// at wled.cpp deserializeConfigFromFS() and calls UsermodManager::setup() after,
// so the ordering this relies on is guaranteed rather than lucky.
inline uint16_t *cfxBankSlots() { static uint16_t s[CFX_BANK_SLOTS] = {0}; return s; }

// True once the bank usermod has read config. Until then nothing has told us
// what the user wants, and a fresh install has no config at all - see the note
// on the default in cfxBankWants().
inline bool &cfxBankConfigured() { static bool c = false; return c; }

// Display name is everything before the '@' in the metadata string.
inline uint16_t cfxBankHash(const char *data) {
  uint16_t h = 0x1F35;                       // FNV-ish, folded to 16 bits
  for (const char *p = data; *p && *p != '@'; ++p) {
    h ^= (uint8_t)*p;
    h = (uint16_t)(h * 31u + 7u);
  }
  return h ? h : 1;                          // 0 is reserved for "empty slot"
}

inline void cfxBankName(const char *data, char *out, size_t n) {
  size_t i = 0;
  for (const char *p = data; *p && *p != '@' && i + 1 < n; ++p) out[i++] = *p;
  out[i] = 0;
}

// Should this effect claim a slot?
//
// With no configuration yet - a fresh flash, or the bank usermod disabled - the
// honest answer is yes. Defaulting to "off" would leave a first-time user with
// a cube that lights nothing and no clue why, and the ceiling still protects
// them: past 39 the surplus simply does not register, exactly as before the
// bank existed. So an unconfigured device behaves like the old build.
inline bool cfxBankWants(uint16_t hash) {
  if (!cfxBankConfigured()) return true;
  const uint16_t *s = cfxBankSlots();
  for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) if (s[i] == hash) return true;
  return false;
}

// Record an effect on the roster. Registration with WLED happens later, in slot
// order, so this only files the effect away. Registering here instead would put
// IDs back at the mercy of link order, which is the thing the slots exist to
// take away.
inline void cfxBankAdd(void (*fn)(), const char *data) {
  uint16_t &n = cfxBankCount();
  if (n >= CFX_BANK_MAX_FX) return;          // roster full: compiled but unreachable
  CfxBankEntry &e = cfxBankRoster()[n++];
  e.hash   = cfxBankHash(data);
  e.data   = data;
  e.fn     = fn;
  e.placed = false;
}

// ---------------------------------------------------------------------------
// How an effect file joins the bank
// ---------------------------------------------------------------------------
// One global per effect file:
//
//     static CfxBankReg cube_fx_plasma_reg(&mode_plasma, _data_FX_MODE_PLASMA);
//
// It registers from a STATIC CONSTRUCTOR, not from setup(), and that timing is
// the point. Every static constructor in the binary runs before WLED's setup()
// does, so by the time the bank's own setup() is called the roster is already
// complete - no matter which order the linker put the translation units in. Had
// effects reported themselves from setup() instead, the bank could easily run
// before half of them and would place slots against a roster still filling up.
//
// The Meyers-singleton accessors above (function-local statics) are what make
// this safe: they construct on first use, so a static constructor in another
// file cannot touch the roster before it exists.
//
// This also replaces the per-effect Usermod subclass each file used to carry,
// which means 25 fewer usermods in WLED's registry.
struct CfxBankReg {
  CfxBankReg(void (*fn)(), const char *data) { cfxBankAdd(fn, data); }
};

// Place the chosen effects, in slot order. Called once from the bank usermod's
// setup(), which keeps registration inside UsermodManager::setup() exactly where
// it has always happened - beginStrip() applies the boot preset BEFORE usermod
// setup runs, so anything later would be too late for a preset to resolve.
inline void cfxBankApply() {
  CfxBankEntry *r = cfxBankRoster();
  const uint16_t n = cfxBankCount();

  if (!cfxBankConfigured()) {                 // no config yet: behave like the old build
    for (uint16_t i = 0; i < n; i++)
      r[i].placed = (strip.addEffect(255, r[i].fn, r[i].data) != 255);
    return;
  }

  const uint16_t *s = cfxBankSlots();
  for (uint8_t k = 0; k < CFX_BANK_SLOTS; k++) {
    if (!s[k]) continue;                      // empty slot
    for (uint16_t i = 0; i < n; i++) {
      if (r[i].hash != s[k] || r[i].placed) continue;
      r[i].placed = (strip.addEffect(255, r[i].fn, r[i].data) != 255);
      break;                                  // a hash names one effect
    }
  }
}

// How many slots actually landed - the honest number for the settings page,
// since addEffect can still refuse if the device is full for other reasons.
inline uint16_t cfxBankPlacedCount() {
  uint16_t c = 0;
  for (uint16_t i = 0; i < cfxBankCount(); i++) if (cfxBankRoster()[i].placed) c++;
  return c;
}
