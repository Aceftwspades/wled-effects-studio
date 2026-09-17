#pragma once
// Arduino's flash-string machinery, reduced to nothing.
//
// On the ESP32 these macros park constants in flash and read them back a byte
// at a time. A host build has one flat address space, so every one of them is
// the identity - but they still have to EXIST, because the effect sources and
// WLED's own math library are written against them.
#include <stdint.h>
#include <string.h>

#define PROGMEM
#define PGM_P            const char *
#define PSTR(s)          (s)
#define FPSTR(p)         (p)
#define F(s)             (s)
#define __FlashStringHelper char

static inline uint8_t  pgm_read_byte(const void *p)      { return *(const uint8_t  *)p; }
static inline uint8_t  pgm_read_byte_near(const void *p) { return *(const uint8_t  *)p; }
static inline uint16_t pgm_read_word(const void *p)      { return *(const uint16_t *)p; }
static inline uint32_t pgm_read_dword(const void *p)     { return *(const uint32_t *)p; }
static inline float    pgm_read_float(const void *p)     { return *(const float    *)p; }
static inline void    *pgm_read_ptr(const void *p)       { return *(void * const  *)p; }

#define memcpy_P         memcpy
#define strlen_P         strlen
#define strcpy_P         strcpy
#define snprintf_P       snprintf
#define strncmp_P        strncmp
