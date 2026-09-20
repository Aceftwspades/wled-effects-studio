#include "wled.h"
#include "cube_fx_bank.h"
#include "cube_fx_common.h"

// The one definition of the six-face flag (cube_fx_common.h): the build's
// default, then whatever the settings page says.
#ifndef CFX_SIX_FACES
#define CFX_SIX_FACES 0
#endif
bool cfx_sixFaces = (CFX_SIX_FACES != 0);

// ===========================================================================
// cube_fx_bank.cpp - the settings page for the effect slots
// ===========================================================================
// See cube_fx_bank.h for why the bank exists and how the roster is built. This
// file is the usermod around it: it loads the slot list from config, places the
// chosen effects in order during setup(), and renders the settings UI.
//
// ---------------------------------------------------------------------------
// WHY A SLOT LIST AND NOT A ROW OF CHECKBOXES
// ---------------------------------------------------------------------------
// Checkboxes would answer "which effects" in a third of the page weight. They
// cannot answer "in what order", and order is half the value here: registration
// order becomes effect-ID order, which becomes the order effects appear in the
// WLED list and in the on-cube menu. Left to the linker that order is
// unspecified and shifts between builds. A slot list makes it yours.
//
// ---------------------------------------------------------------------------
// THE PAGE IS HEAVY, ON PURPOSE
// ---------------------------------------------------------------------------
// CFX_BANK_SLOTS dropdowns each listing every compiled effect is on the order of
// a thousand addOption() calls streamed from the ESP32, so this page opens
// noticeably slower than the others. That is a deliberate trade: it is a page
// you visit when you change what ships, not one you live in. Everything else
// about the cube is unaffected - the cost is entirely in rendering this form.
// ===========================================================================

class CubeFxBankUsermod : public Usermod {
 private:
  bool     enabled = true;
  bool     sixFaces = (CFX_SIX_FACES != 0);   // the bottom face lit, in the net's (2,2) block
  uint16_t slots[CFX_BANK_SLOTS] = {0};

  static const char _name[];

  // Slot keys are s00..s35 so they sort correctly in the JSON and in the form.
  static void slotKey(uint8_t i, char *out) {
    out[0] = 's'; out[1] = (char)('0' + (i / 10)); out[2] = (char)('0' + (i % 10)); out[3] = 0;
  }

 public:
  void setup() override {
    if (!enabled) {
      // Disabled means "get out of the way", not "register nothing" - a user who
      // switches the bank off wants the old behaviour back, not a dark cube.
      cfxBankConfigured() = false;
    }
    cfxBankApply();
  }

  void loop() override { cfx_geomPoll(); }        // the shape table, /geometry.bin, read when it changes

  void addToConfig(JsonObject &root) override {
    JsonObject top = root.createNestedObject(FPSTR(_name));
    top[F("enabled")] = enabled;
    top[F("six_faces")] = sixFaces;
    char k[4];
    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) { slotKey(i, k); top[k] = slots[i]; }
  }

  bool readFromConfig(JsonObject &root) override {
    JsonObject top = root[FPSTR(_name)];
    if (top.isNull()) return false;

    getJsonValue(top[F("enabled")], enabled, true);
    getJsonValue(top[F("six_faces")], sixFaces, (bool)(CFX_SIX_FACES != 0));
    cfx_sixFaces = sixFaces;
    char k[4];
    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) {
      slotKey(i, k);
      uint16_t v = 0;
      getJsonValue(top[k], v, (uint16_t)0);
      slots[i] = v;
    }

    // Publish before any effect's setup() runs. WLED reads config in
    // deserializeConfigFromFS() and calls UsermodManager::setup() afterwards, so
    // this ordering is guaranteed by the boot sequence rather than by luck.
    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) cfxBankSlots()[i] = slots[i];
    // A bank with every slot empty has not been configured, whatever wrote
    // the key: WLED saves the whole usermod block whenever any setting in it
    // is saved (the studio's six-face push, for one), and an all-zero block
    // read back on the next boot must not turn every effect off. No slots
    // chosen means every effect registers, as before the bank existed.
    bool chosen = false;
    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) if (slots[i]) chosen = true;
    cfxBankConfigured() = enabled && chosen;
    return true;
  }

  void addToJsonInfo(JsonObject &root) override {
    JsonObject user = root[F("u")];
    if (user.isNull()) user = root.createNestedObject(F("u"));
    JsonArray s = user.createNestedArray(F("Cube FX slots"));
    char buf[48];
    if (!enabled) {
      snprintf_P(buf, sizeof(buf), PSTR("off - all %u registered"), (unsigned)cfxBankCount());
    } else if (!cfxBankConfigured()) {
      snprintf_P(buf, sizeof(buf), PSTR("none chosen - all %u registered"), (unsigned)cfxBankCount());
    } else {
      snprintf_P(buf, sizeof(buf), PSTR("%u of %u placed"),
                 (unsigned)cfxBankPlacedCount(), (unsigned)cfxBankCount());
    }
    s.add(buf);
    // Anything compiled but not placed is invisible in the effect list, and the
    // whole point of the bank is that this is a decision rather than a surprise.
    const uint16_t missing = (uint16_t)(cfxBankCount() - cfxBankPlacedCount());
    s.add(missing ? F(" - reboot to apply changes") : F(""));

    // How much room is actually left on THIS build, counted rather than guessed.
    //
    // Working it out from the source is unreliable: several built-ins sit behind
    // #ifdefs that are off by default, so counting addEffect() calls in FX.cpp
    // over-states how many slots the built-ins really occupy and understates the
    // headroom. The device knows exactly. Free slots are the RSVD placeholders
    // still sitting inside the initial table plus whatever is left below the
    // 255-entry hard ceiling, which is precisely what addEffect() will use.
    unsigned used = strip.getModeCount(), rsvd = 0;
    for (unsigned i = 1; i < used; i++) {
      const char *d = strip.getModeData(i);
      if (d && pgm_read_byte(d) == 'R' && pgm_read_byte(d + 1) == 'S' &&
          pgm_read_byte(d + 2) == 'V' && pgm_read_byte(d + 3) == 'D') rsvd++;
    }
    JsonArray f = user.createNestedArray(F("Cube FX slots free"));
    char fb[52];
    snprintf_P(fb, sizeof(fb), PSTR("%u  (%u modes, %u gaps + %u above)"),
               (unsigned)(rsvd + (255 - used)), used, rsvd, (unsigned)(255 - used));
    f.add(fb);
    // the Studio Script effect's frame budget: a program too heavy for the
    // chip runs at half or a quarter of the width, and this is where it says so
    JsonArray sc = user.createNestedArray(F("Studio Script"));
    if (cfx_scriptStride <= 1) snprintf_P(fb, sizeof(fb), PSTR("full resolution, %u.%u ms a frame"), (unsigned)(cfx_scriptTook / 1000), (unsigned)(cfx_scriptTook / 100 % 10));
    else snprintf_P(fb, sizeof(fb), PSTR("1/%u width - over the frame budget, %u.%u ms a frame"), (unsigned)cfx_scriptStride, (unsigned)(cfx_scriptTook / 1000), (unsigned)(cfx_scriptTook / 100 % 10));
    sc.add(fb);
  }

  void appendConfigData(Print &s) override {
    auto jsq = [&](const char *t) {
      for (const char *p = t; *p; ++p) { if (*p == '\'' || *p == '\\') s.print('\\'); s.print(*p); }
    };

    // --- the dropdowns -------------------------------------------------------
    // The option list is emitted ONCE as a JS array and then cloned into every
    // slot select, rather than re-printed into all CFX_BANK_SLOTS of them.
    //
    // The naive way - a full addOption() per effect per slot - is ~36 x 35
    // script lines, tens of KB, and the whole usermod settings block is wrapped
    // in one function that must parse as a unit. Past a certain size the
    // generated script does not arrive intact, and a script cut off mid-call
    // silently fails to run, leaving every field as the raw number input it
    // started life as. That is the "dropdowns turned into numbers" failure.
    // One shared array is ~36x smaller and also renders far faster.
    CfxBankEntry *r = cfxBankRoster();
    const uint16_t n = cfxBankCount();
    char nm[40], key[4];

    s.print(F("var CFXO=[['-- empty --',0]"));
    for (uint16_t e = 0; e < n; e++) {
      cfxBankName(r[e].data, nm, sizeof(nm));
      s.print(F(",['")); jsq(nm); s.print(F("',")); s.print(r[e].hash); s.print(F("]"));
    }
    s.print(F("];var CFXD=[];"));

    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) {
      slotKey(i, key);
      s.print(F("CFXD.push(addDropdown('")); s.print(FPSTR(_name));
      s.print(F("','")); s.print(key); s.print(F("')); "));
    }
    s.print(F("for(var _k=0;_k<CFXD.length;_k++){var _s=CFXD[_k];if(!_s)continue;"
              "for(var _m=0;_m<CFXO.length;_m++)addOption(_s,CFXO[_m][0],CFXO[_m][1]);}"));

    // --- grey-out ------------------------------------------------------------
    // An effect chosen in one slot is disabled in the others, so two slots
    // cannot silently spend themselves on the same effect. Disabled rather than
    // hidden: options keep their positions, so the list does not reshuffle under
    // the cursor while you are working down it.
    //
    // The current slot's own value is never disabled, or reopening a select
    // would show it blank.
    s.print(F(
      "if(!window.cfxBankSync){window.cfxBankSync=function(){"
      "var f=document.getElementsByTagName('select'),u={},i,j,o;"
      "for(i=0;i<f.length;i++){if(f[i].name&&f[i].name.indexOf('CubeFXBank:s')==0){"
      "if(f[i].value!='0')u[f[i].value]=1;}}"
      "for(i=0;i<f.length;i++){if(f[i].name&&f[i].name.indexOf('CubeFXBank:s')==0){"
      "for(j=0;j<f[i].options.length;j++){o=f[i].options[j];"
      "o.disabled=(o.value!='0'&&u[o.value]&&o.value!=f[i].value);}}}"
      "var c=0;for(i=0;i<f.length;i++){if(f[i].name&&f[i].name.indexOf('CubeFXBank:s')==0&&f[i].value!='0')c++;}"
      "var t=document.getElementById('cfxBankCount');if(t)t.innerHTML=c+' of ' + f.length;"
      "};"
      "document.addEventListener('change',function(e){"
      "if(e.target&&e.target.name&&e.target.name.indexOf('CubeFXBank:s')==0)window.cfxBankSync();});"
      "setTimeout(window.cfxBankSync,300);}"));

    // --- Assign all / Clear all ----------------------------------------------
    // A fresh build otherwise means setting every slot by hand. Assign all
    // fills each EMPTY slot with the next unused effect in roster order and
    // leaves your existing picks untouched, so you populate once and then edit
    // the few you care about. Clear all empties them. Both are one-shot actions
    // on the live dropdowns - nothing is saved until you press Save - so a
    // button is the honest control, not a checkbox that would imply a stored
    // state. They close over the CFXO option list emitted above.
    s.print(F(
      "window.cfxBankAssign=function(){"
      "var f=Array.prototype.slice.call(document.getElementsByTagName('select'))"
      ".filter(function(x){return x.name&&x.name.indexOf('CubeFXBank:s')==0;});"
      "f.sort(function(a,b){return a.name<b.name?-1:1;});"
      "var u={};f.forEach(function(s){if(s.value!='0')u[s.value]=1;});"
      "var oi=1;f.forEach(function(s){if(s.value!='0')return;"
      "while(oi<CFXO.length&&u[CFXO[oi][1]])oi++;"
      "if(oi<CFXO.length){s.value=String(CFXO[oi][1]);u[CFXO[oi][1]]=1;oi++;}});"
      "window.cfxBankSync();};"
      "window.cfxBankClear=function(){"
      "var f=document.getElementsByTagName('select');for(var i=0;i<f.length;i++)"
      "{if(f[i].name&&f[i].name.indexOf('CubeFXBank:s')==0)f[i].value='0';}"
      "window.cfxBankSync();};"
      "(function(){var h=document.getElementsByName('CubeFXBank:enabled')[0];if(!h)return;"
      "var bar=document.createElement('div');bar.style.margin='8px 0';"
      "var mk=function(t,fn){var b=document.createElement('button');b.type='button';"
      "b.innerHTML=t;b.onclick=fn;b.style.marginRight='8px';return b;};"
      "bar.appendChild(mk('Assign all',window.cfxBankAssign));"
      "bar.appendChild(mk('Clear all',window.cfxBankClear));"
      "var c=document.createElement('span');c.id='cfxBankCount';bar.appendChild(c);"
      "h.parentNode.insertBefore(bar,h.nextSibling);})();"));

    auto info = [&](const char *k, const char *html) {
      s.print(F("addInfo('")); s.print(FPSTR(_name)); s.print(F(":")); s.print(k);
      s.print(F("',1,'")); jsq(html); s.print(F("');"));
    };
    // All guidance rides on the ENABLED field, which is above the slot list.
    // Anchoring it to a slot instead puts the text after that slot's row - which
    // is the afterend behaviour of addInfo - and splits the list in two.
    info("enabled",
         "ticked, the slots below choose which effects appear and in what order - "
         "<b>on reboot</b>. An effect used in another slot is greyed out; leave a slot "
         "empty to keep it free. Untick to ignore the slots and register every "
         "compiled effect, as before the bank existed.");
    info("six_faces",
         "the cube has a lit bottom face, wired as the bottom-right corner block of the "
         "net (the block under EAST, right of SOUTH). Untick for the usual five faces.");
  }

  uint16_t getId() override { return USERMOD_ID_UNSPECIFIED; }
};

const char CubeFxBankUsermod::_name[] PROGMEM = "CubeFXBank";

static CubeFxBankUsermod cube_fx_bank;
REGISTER_USERMOD(cube_fx_bank);
