#pragma once
// Just enough Arduino for wled_math.cpp, which wants it only for PI.
// Compiling that file rather than re-deriving its trig is deliberate: sin8_t
// and friends are lookup-and-interpolate, not std::sin, and effects are tuned
// against their exact curve.
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <algorithm>
#include "pgmspace.h"

#ifndef PI
  #define PI 3.1415926535897932384626433832795
#endif
#ifndef M_TWOPI
  #define M_TWOPI (2.0 * PI)
#endif
#ifndef HALF_PI
  #define HALF_PI (PI / 2.0)
#endif

using std::min;
using std::max;
