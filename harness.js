// Measurement harness for tuning passes. Not part of the simulator UI - load it
// from the console (or a driving tool) when you want numbers instead of eyes.
//
//   __probe({fx:'black hole', ms:16000})
//
// Steps the simulated clock explicitly rather than riding requestAnimationFrame,
// because a background tab throttles rAF and every measurement taken that way is
// silently meaningless.
//
// Reported per sample, over all lit pixels and over the lid alone:
//   mean    average luma
//   sigma   spatial standard deviation of luma - "how much structure"
//   dark    % below luma 16   - the black gaps that make a pattern readable
//   bright  % above luma 200  - highlights
//   sat     mean HSV saturation of pixels above luma 32 - colour survival
window.__probe = function (opts) {
  opts = opts || {};
  const sel = document.getElementById('fx');
  let idx = -1;
  for (const o of sel.options)
    if (o.textContent.toLowerCase().includes((opts.fx || 'black hole').toLowerCase())) { idx = +o.value; break; }
  if (idx < 0) return 'no such effect';
  sel.value = idx; sel.onchange();
  if (opts.pal !== undefined) document.getElementById('pal').value = opts.pal;
  if (opts.params) for (const k in opts.params) fx[k] = opts.params[k];
  push();
  M.ccall('simSelect');
  simMs = 0; lastBeat = -1e9;
  autoBeat = (opts.beat === undefined) ? true : !!opts.beat;

  const N = cols * rows, lit = [], lidx = [];
  for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
    const bx = (x / B) | 0, by = (y / B) | 0;
    if (bx !== 1 && by !== 1) continue;
    lit.push(y * cols + x);
  }
  for (let y = B; y < 2 * B; y++) for (let x = B; x < 2 * B; x++) lidx.push(y * cols + x);

  const stat = (list, u32) => {
    let n = 0, s = 0, ss = 0, dark = 0, bright = 0, sat = 0, ns = 0;
    for (const i of list) {
      const c = u32[i], r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
      const L = (r * 54 + g * 183 + b * 19) >> 8;
      n++; s += L; ss += L * L;
      if (L < 16) dark++;
      if (L > 200) bright++;
      if (L > 32) { const mx = Math.max(r, g, b), mn = Math.min(r, g, b); sat += mx ? (mx - mn) * 255 / mx : 0; ns++; }
    }
    const mean = s / n;
    return { mean: +mean.toFixed(1), sigma: +Math.sqrt(ss / n - mean * mean).toFixed(1),
             dark: +(100 * dark / n).toFixed(1), bright: +(100 * bright / n).toFixed(1),
             sat: +(ns ? sat / ns : 0).toFixed(0) };
  };

  const warm = opts.warm === undefined ? 60 : opts.warm;
  const total = opts.ms || 16000, out = [];
  for (let f = 0; f * 23 < total + warm * 23; f++) {
    pushAudio(); frame(23);
    if (f >= warm && (f - warm) % 40 === 0) {
      const u32 = new Uint32Array(M.HEAPU32.buffer, px32, N);
      out.push({ t: Math.round(simMs), all: stat(lit, u32), lid: stat(lidx, u32) });
    }
  }
  return out;
};

// Average of a probe run, so runs can be compared at a glance.
window.__avg = function (rows) {
  const mk = k => {
    const o = {};
    for (const f of ['mean', 'sigma', 'dark', 'bright', 'sat'])
      o[f] = +(rows.reduce((a, r) => a + r[k][f], 0) / rows.length).toFixed(1);
    return o;
  };
  return { all: mk('all'), lid: mk('lid') };
};

// Luma histogram of the lid at the current frame, in eight buckets of 32.
window.__lidHist = function () {
  const u32 = new Uint32Array(M.HEAPU32.buffer, px32, cols * rows);
  const h = new Array(8).fill(0); let n = 0, mx = 0;
  for (let y = B; y < 2 * B; y++) for (let x = B; x < 2 * B; x++) {
    const c = u32[y * cols + x], r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
    const L = (r * 54 + g * 183 + b * 19) >> 8;
    h[Math.min(7, L >> 5)]++; n++; if (L > mx) mx = L;
  }
  return { pct: h.map(v => +(100 * v / n).toFixed(1)), max: mx };
};
'harness ready';
