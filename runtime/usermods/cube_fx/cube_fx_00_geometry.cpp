#include "wled.h"
#include "cube_fx_common.h"

// ===========================================================================
// The shape: a position for every pixel
// ===========================================================================
// WLED knows a segment as a strip or a matrix. The cube effects know a
// cube because cfx_pos() works a face out from the pixel's place on the
// net. Any other shape - a sphere, a strip run round a tree, a prop from a
// 3-D program - has no such rule, so the studio sends its positions as a
// table, `/geometry.bin`, and cfx_pos() reads that instead when one is
// loaded for the segment's size. Every effect and every graph node that
// asks where a pixel is (Position, Direction, Cube face...) then sees the
// real shape, and the Studio Script effect's fixed registers do too.
//
// The file: "STGM", u8 version (1), u16 cols, u16 rows, u16 flags (bit 0:
// normals follow the positions; bit 1: parts follow those), then cols*rows
// entries of int8 x, y, z in the -1..1 box scaled by 127 (an unlit pixel
// of the net is still an entry: zeros), then, with bit 0, cols*rows entries
// of int8 nx, ny, nz, then, with bit 1, cols*rows entries of u8 part id
// and u8 place along the part (0..255). Without normals the effects take
// the direction from the centre; without parts every pixel is part 0 of 1.
//
// The device reads the file again whenever it changes (checked every two
// seconds from the bank usermod's loop); the simulator is handed the same
// bytes in memory (simGeometryLoad) so a shape previews as it will run.
// ===========================================================================

const int8_t *cfx_geomTab = nullptr;
const int8_t *cfx_geomNrm = nullptr;
const uint8_t *cfx_geomPart = nullptr;
uint16_t cfx_geomCols = 0, cfx_geomRows = 0, cfx_geomParts = 0;
static uint8_t *geomBuf = nullptr;
static size_t geomLen = 0;

static bool geomParse() {
  cfx_geomTab = cfx_geomNrm = nullptr; cfx_geomPart = nullptr; cfx_geomCols = cfx_geomRows = cfx_geomParts = 0;
  if (!geomBuf || geomLen < 11 || memcmp(geomBuf, "STGM", 4) != 0 || geomBuf[4] != 1) return false;
  const uint16_t cols = geomBuf[5] | (geomBuf[6] << 8), rows = geomBuf[7] | (geomBuf[8] << 8);
  const uint16_t flags = geomBuf[9] | (geomBuf[10] << 8);
  const size_t n = (size_t)cols * rows;
  if (n == 0 || n > 65536) return false;
  size_t need = 11 + n * 3 + ((flags & 1) ? n * 3 : 0) + ((flags & 2) ? n * 2 : 0);
  if (geomLen < need) return false;
  cfx_geomTab = (const int8_t *)(geomBuf + 11);
  cfx_geomNrm = (flags & 1) ? cfx_geomTab + n * 3 : nullptr;
  if (flags & 2) {
    cfx_geomPart = (const uint8_t *)(geomBuf + 11 + n * 3 + ((flags & 1) ? n * 3 : 0));
    uint16_t mx = 0;
    for (size_t i = 0; i < n; i++) if (cfx_geomPart[i * 2] > mx) mx = cfx_geomPart[i * 2];
    cfx_geomParts = mx + 1;
  }
  cfx_geomCols = cols; cfx_geomRows = rows;
  return true;
}

static void geomTake(uint8_t *buf, size_t n) {
  free(geomBuf); geomBuf = buf; geomLen = n;
  geomParse();
}

#ifdef CFX_SIM
extern "C" void simGeometryLoad(const uint8_t *bytes, int n) {
  if (!bytes || n <= 0) { geomTake(nullptr, 0); return; }
  uint8_t *buf = (uint8_t *)malloc(n);
  if (!buf) return;
  memcpy(buf, bytes, n);
  geomTake(buf, n);
}
extern "C" int simGeometryOk() { return cfx_geomTab ? 1 : 0; }
void cfx_geomPoll() {}
#else
void cfx_geomPoll() {
  static uint32_t last = 0;
  if (millis() - last < 2000) return;
  last = millis();
  File f = WLED_FS.open("/geometry.bin", "r");
  if (!f) { if (geomBuf) geomTake(nullptr, 0); return; }        // the file removed: back to the rule
  size_t n = f.size();
  if (n < 11 || n > 11 + 65536 * 6) { f.close(); return; }
  uint8_t *buf = (uint8_t *)malloc(n);
  if (!buf) { f.close(); return; }
  size_t got = f.read(buf, n);
  f.close();
  if (got == n && !(geomBuf && geomLen == n && memcmp(geomBuf, buf, n) == 0)) geomTake(buf, n);   // a read, not a rebuild, when unchanged
  else free(buf);
}
#endif
