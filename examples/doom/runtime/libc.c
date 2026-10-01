/* The C library subset doomgeneric imports, for the bare DOOM machine. Output goes
   to the console MMIO register; the only readable file is the preloaded WAD. */
#include <ctype.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "machine.h"

#define MMIO(offset) (*(volatile uint32_t *)(MMIO_BASE + (offset)))

int errno;

/* ---- memory ---- */

void *memcpy(void *to, const void *from, size_t n)
{
    uint8_t *d = to;
    const uint8_t *s = from;
    if ((((uintptr_t)d ^ (uintptr_t)s) & 3) == 0) {
        while (n && ((uintptr_t)d & 3)) { *d++ = *s++; n--; }
        uint32_t *dw = (uint32_t *)d;
        const uint32_t *sw = (const uint32_t *)s;
        for (; n >= 16; n -= 16) {
            dw[0] = sw[0]; dw[1] = sw[1]; dw[2] = sw[2]; dw[3] = sw[3];
            dw += 4; sw += 4;
        }
        for (; n >= 4; n -= 4) *dw++ = *sw++;
        d = (uint8_t *)dw;
        s = (const uint8_t *)sw;
    }
    while (n--) *d++ = *s++;
    return to;
}

void *memmove(void *to, const void *from, size_t n)
{
    uint8_t *d = to;
    const uint8_t *s = from;
    if (d <= s || d >= s + n) return memcpy(to, from, n);
    while (n--) d[n] = s[n];
    return to;
}

void *memset(void *to, int value, size_t n)
{
    uint8_t *d = to;
    while (n && ((uintptr_t)d & 3)) { *d++ = (uint8_t)value; n--; }
    uint32_t word = (uint8_t)value * 0x01010101u;
    uint32_t *dw = (uint32_t *)d;
    for (; n >= 4; n -= 4) *dw++ = word;
    d = (uint8_t *)dw;
    while (n--) *d++ = (uint8_t)value;
    return to;
}

int memcmp(const void *a, const void *b, size_t n)
{
    const uint8_t *x = a, *y = b;
    for (; n; n--, x++, y++)
        if (*x != *y) return *x - *y;
    return 0;
}

void *memchr(const void *s, int c, size_t n)
{
    const uint8_t *p = s;
    for (; n; n--, p++)
        if (*p == (uint8_t)c) return (void *)p;
    return NULL;
}

/* ---- strings ---- */

size_t strlen(const char *s)
{
    const char *p = s;
    while (*p) p++;
    return p - s;
}

char *strcpy(char *to, const char *from)
{
    char *d = to;
    while ((*d++ = *from++)) {}
    return to;
}

char *strncpy(char *to, const char *from, size_t n)
{
    size_t i = 0;
    for (; i < n && from[i]; i++) to[i] = from[i];
    for (; i < n; i++) to[i] = 0;
    return to;
}

char *strcat(char *to, const char *from)
{
    strcpy(to + strlen(to), from);
    return to;
}

char *strncat(char *to, const char *from, size_t n)
{
    char *d = to + strlen(to);
    while (n-- && *from) *d++ = *from++;
    *d = 0;
    return to;
}

int strcmp(const char *a, const char *b)
{
    while (*a && *a == *b) a++, b++;
    return (uint8_t)*a - (uint8_t)*b;
}

int strncmp(const char *a, const char *b, size_t n)
{
    for (; n; n--, a++, b++)
        if (*a != *b || !*a) return (uint8_t)*a - (uint8_t)*b;
    return 0;
}

int strcasecmp(const char *a, const char *b)
{
    while (*a && tolower(*a) == tolower(*b)) a++, b++;
    return tolower((uint8_t)*a) - tolower((uint8_t)*b);
}

int strncasecmp(const char *a, const char *b, size_t n)
{
    for (; n; n--, a++, b++)
        if (tolower(*a) != tolower(*b) || !*a)
            return tolower((uint8_t)*a) - tolower((uint8_t)*b);
    return 0;
}

char *strchr(const char *s, int c)
{
    for (;; s++) {
        if (*s == (char)c) return (char *)s;
        if (!*s) return NULL;
    }
}

char *strrchr(const char *s, int c)
{
    const char *found = NULL;
    for (;; s++) {
        if (*s == (char)c) found = s;
        if (!*s) return (char *)found;
    }
}

char *strstr(const char *haystack, const char *needle)
{
    size_t n = strlen(needle);
    for (; *haystack; haystack++)
        if (!strncmp(haystack, needle, n)) return (char *)haystack;
    return n ? NULL : (char *)haystack;
}

char *strdup(const char *s)
{
    size_t n = strlen(s) + 1;
    char *copy = malloc(n);
    if (copy) memcpy(copy, s, n);
    return copy;
}

char *strerror(int error)
{
    return error == ENOENT ? "No such file" : "Error";
}

/* ---- heap: a bump allocator; only the newest block can be freed or grown ---- */

extern char _end[];
static uintptr_t heap_top;
static uintptr_t last_block;
uintptr_t heap_high_water;

typedef struct { uint32_t size, pad[3]; } block_t;

void *malloc(size_t size)
{
    if (!heap_top) heap_top = ((uintptr_t)_end + 15) & ~(uintptr_t)15;
    size = (size + 15) & ~(size_t)15;
    if (size > HEAP_LIMIT - heap_top - sizeof(block_t)) {
        errno = 12;
        return NULL;
    }
    block_t *block = (block_t *)heap_top;
    block->size = size;
    last_block = heap_top;
    heap_top += sizeof(block_t) + size;
    if (heap_top > heap_high_water) heap_high_water = heap_top;
    return block + 1;
}

void free(void *pointer)
{
    if (pointer && (uintptr_t)pointer - sizeof(block_t) == last_block) {
        heap_top = last_block;
        last_block = 0;
    }
}

void *calloc(size_t count, size_t size)
{
    size_t total = count * size;
    void *pointer = malloc(total);
    if (pointer) memset(pointer, 0, total);
    return pointer;
}

void *realloc(void *pointer, size_t size)
{
    if (!pointer) return malloc(size);
    block_t *block = (block_t *)pointer - 1;
    size_t rounded = (size + 15) & ~(size_t)15;
    if ((uintptr_t)block == last_block && rounded <= HEAP_LIMIT - (uintptr_t)pointer) {
        block->size = rounded;
        heap_top = (uintptr_t)pointer + rounded;
        if (heap_top > heap_high_water) heap_high_water = heap_top;
        return pointer;
    }
    if (rounded <= block->size) return pointer;
    void *copy = malloc(size);
    if (copy) memcpy(copy, pointer, block->size);
    return copy;
}

/* ---- process ---- */

void exit(int code)
{
    MMIO(MMIO_EXIT) = (uint32_t)code;
    for (;;) {}
}

void abort(void) { exit(134); }

void __assert_fail(const char *expression, const char *file, int line)
{
    printf("assertion failed: %s (%s:%d)\n", expression, file, line);
    abort();
}

char *getenv(const char *name) { (void)name; return NULL; }
int system(const char *command) { (void)command; return -1; }
int mkdir(const char *path, mode_t mode) { (void)path; (void)mode; return 0; }
int remove(const char *path) { (void)path; return -1; }
int rename(const char *from, const char *to) { (void)from; (void)to; return -1; }
int abs(int value) { return value < 0 ? -value : value; }
long labs(long value) { return value < 0 ? -value : value; }

/* ---- numbers ---- */

unsigned long strtoul(const char *s, char **end, int base)
{
    while (isspace(*s)) s++;
    if (*s == '+') s++;
    if ((base == 0 || base == 16) && s[0] == '0' && (s[1] | 32) == 'x' && isxdigit(s[2])) {
        s += 2;
        base = 16;
    } else if (base == 0) {
        base = s[0] == '0' ? 8 : 10;
    }
    unsigned long value = 0;
    for (;; s++) {
        int digit = isdigit(*s) ? *s - '0' : isalpha(*s) ? (*s | 32) - 'a' + 10 : 99;
        if (digit >= base) break;
        value = value * base + digit;
    }
    if (end) *end = (char *)s;
    return value;
}

long strtol(const char *s, char **end, int base)
{
    while (isspace(*s)) s++;
    int negative = *s == '-';
    if (negative) s++;
    long value = (long)strtoul(s, end, base);
    return negative ? -value : value;
}

int atoi(const char *s) { return (int)strtol(s, NULL, 10); }
long atol(const char *s) { return strtol(s, NULL, 10); }

double atof(const char *s)
{
    char *end;
    double value = (double)strtol(s, &end, 10);
    if (*end == '.') {
        double scale = 0.1;
        int negative = value < 0 || s[0] == '-';
        for (end++; isdigit(*end); end++, scale /= 10)
            value += (negative ? -scale : scale) * (*end - '0');
    }
    return value;
}

/* ---- files: the WAD (read-only, from RAM) and console streams ---- */

struct FILE {
    int console;
    const uint8_t *data;
    long size, position;
};

static FILE console_stream = {1, NULL, 0, 0};
static FILE wad_stream;
FILE *stdin = &console_stream, *stdout = &console_stream, *stderr = &console_stream;

FILE *fopen(const char *path, const char *mode)
{
    const char *base = strrchr(path, '/');
    base = base ? base + 1 : path;
    const uint32_t *header = (const uint32_t *)WAD_HEADER;
    if (mode[0] == 'r' && !strcasecmp(base, "doom1.wad") && header[0] == WAD_MAGIC) {
        wad_stream = (FILE){0, (const uint8_t *)WAD_DATA, (long)header[1], 0};
        return &wad_stream;
    }
    errno = ENOENT;
    return NULL;
}

int fclose(FILE *f) { (void)f; return 0; }
int fflush(FILE *f) { (void)f; return 0; }

size_t fread(void *buffer, size_t size, size_t count, FILE *f)
{
    if (f->console || !size) return 0;
    long available = f->size - f->position;
    size_t items = count;
    if ((long)(size * count) > available) items = available / size;
    memcpy(buffer, f->data + f->position, items * size);
    f->position += items * size;
    return items;
}

int putchar(int c)
{
    MMIO(MMIO_CONSOLE) = (uint8_t)c;
    return (uint8_t)c;
}

size_t fwrite(const void *buffer, size_t size, size_t count, FILE *f)
{
    if (!f->console) return 0;
    const char *p = buffer;
    for (size_t i = 0; i < size * count; i++) putchar(p[i]);
    return count;
}

int fseek(FILE *f, long offset, int whence)
{
    long base = whence == SEEK_SET ? 0 : whence == SEEK_CUR ? f->position : f->size;
    if (f->console || base + offset < 0 || base + offset > f->size) return -1;
    f->position = base + offset;
    return 0;
}

long ftell(FILE *f) { return f->position; }

int puts(const char *s)
{
    while (*s) putchar(*s++);
    putchar('\n');
    return 0;
}

/* ---- formatted output ---- */

typedef struct { char *buffer; size_t size, length; } sink_t;

static void emit(sink_t *sink, char c)
{
    if (!sink->buffer) putchar(c);
    else if (sink->length + 1 < sink->size) sink->buffer[sink->length] = c;
    sink->length++;
}

static void emit_padded(sink_t *sink, const char *text, int length, int width, int left, char pad)
{
    if (!left && pad == '0' && (*text == '-' || *text == '+' || *text == ' ') && length) {
        emit(sink, *text++);
        length--;
        width--;
    }
    if (!left) for (int i = length; i < width; i++) emit(sink, pad);
    for (int i = 0; i < length; i++) emit(sink, text[i]);
    if (left) for (int i = length; i < width; i++) emit(sink, ' ');
}

static int format(sink_t *sink, const char *f, va_list args)
{
    char digits[72];
    for (; *f; f++) {
        if (*f != '%') { emit(sink, *f); continue; }
        int left = 0, plus = 0, space = 0, alternate = 0, width = 0, precision = -1, longs = 0;
        char pad = ' ';
        for (;; f++) {
            if (f[1] == '-') left = 1;
            else if (f[1] == '0') pad = '0';
            else if (f[1] == '+') plus = 1;
            else if (f[1] == ' ') space = 1;
            else if (f[1] == '#') alternate = 1;
            else break;
        }
        f++;
        if (*f == '*') { width = va_arg(args, int); if (width < 0) left = 1, width = -width; f++; }
        else while (isdigit(*f)) width = width * 10 + *f++ - '0';
        if (*f == '.') {
            f++;
            precision = 0;
            if (*f == '*') { precision = va_arg(args, int); f++; }
            else while (isdigit(*f)) precision = precision * 10 + *f++ - '0';
        }
        while (*f == 'l' || *f == 'h' || *f == 'z') { if (*f == 'l') longs++; f++; }
        char conversion = *f;
        if (!conversion) break;
        if (conversion == 's') {
            const char *s = va_arg(args, const char *);
            if (!s) s = "(null)";
            int length = 0;
            while (s[length] && (precision < 0 || length < precision)) length++;
            emit_padded(sink, s, length, width, left, ' ');
        } else if (conversion == 'c') {
            char c = (char)va_arg(args, int);
            emit_padded(sink, &c, 1, width, left, ' ');
        } else if (conversion == '%') {
            emit(sink, '%');
        } else if (conversion == 'f') {
            double value = va_arg(args, double);
            if (precision < 0) precision = 6;
            int n = 0;
            if (value < 0) { digits[n++] = '-'; value = -value; }
            unsigned long whole = (unsigned long)value;
            double fraction = value - (double)whole;
            char reversed[24];
            int r = 0;
            do { reversed[r++] = '0' + whole % 10; whole /= 10; } while (whole);
            while (r) digits[n++] = reversed[--r];
            if (precision) digits[n++] = '.';
            for (int i = 0; i < precision && n < 60; i++) {
                fraction *= 10;
                int digit = (int)fraction;
                digits[n++] = '0' + digit;
                fraction -= digit;
            }
            emit_padded(sink, digits, n, width, left, pad);
        } else {
            unsigned long long value;
            int negative = 0, base = 10, upper = conversion == 'X';
            if (conversion == 'd' || conversion == 'i') {
                long long v = longs > 1 ? va_arg(args, long long) : longs ? va_arg(args, long) : va_arg(args, int);
                negative = v < 0;
                value = negative ? 0ull - (unsigned long long)v : (unsigned long long)v;
            } else if (conversion == 'p') {
                value = (uintptr_t)va_arg(args, void *);
                base = 16;
                alternate = 1;
            } else {
                value = longs > 1 ? va_arg(args, unsigned long long)
                        : longs ? va_arg(args, unsigned long) : va_arg(args, unsigned);
                base = conversion == 'o' ? 8 : (conversion == 'x' || conversion == 'X') ? 16 : 10;
            }
            char reversed[24];
            int r = 0;
            while (value) {
                int digit = (int)(value % base);
                reversed[r++] = digit < 10 ? '0' + digit : (upper ? 'A' : 'a') + digit - 10;
                value /= base;
            }
            while (r < precision) reversed[r++] = '0';
            if (!r && precision != 0) reversed[r++] = '0';
            int n = 0;
            if (negative) digits[n++] = '-';
            else if (plus) digits[n++] = '+';
            else if (space) digits[n++] = ' ';
            if (alternate && base == 16) { digits[n++] = '0'; digits[n++] = upper ? 'X' : 'x'; }
            while (r) digits[n++] = reversed[--r];
            emit_padded(sink, digits, n, width, left, precision >= 0 ? ' ' : pad);
        }
    }
    return (int)sink->length;
}

int vsnprintf(char *buffer, size_t size, const char *f, va_list args)
{
    static char empty;
    sink_t sink = {size ? buffer : &empty, size ? size : 1, 0};
    int length = format(&sink, f, args);
    sink.buffer[sink.length < sink.size ? sink.length : sink.size - 1] = 0;
    return length;
}

int snprintf(char *buffer, size_t size, const char *f, ...)
{
    va_list args;
    va_start(args, f);
    int length = vsnprintf(buffer, size, f, args);
    va_end(args);
    return length;
}

int sprintf(char *buffer, const char *f, ...)
{
    va_list args;
    va_start(args, f);
    int length = vsnprintf(buffer, 0x7fffffff, f, args);
    va_end(args);
    return length;
}

int vfprintf(FILE *stream, const char *f, va_list args)
{
    (void)stream;
    sink_t sink = {NULL, 0, 0};
    return format(&sink, f, args);
}

int printf(const char *f, ...)
{
    va_list args;
    va_start(args, f);
    int length = vfprintf(stdout, f, args);
    va_end(args);
    return length;
}

int fprintf(FILE *stream, const char *f, ...)
{
    va_list args;
    va_start(args, f);
    int length = vfprintf(stream, f, args);
    va_end(args);
    return length;
}

/* ---- sscanf: whitespace, literals, %d %i %x %o and %s, as m_misc/m_config use ---- */

int sscanf(const char *s, const char *f, ...)
{
    va_list args;
    va_start(args, f);
    int assigned = 0;
    for (; *f; f++) {
        if (isspace(*f)) { while (isspace(*s)) s++; continue; }
        if (*f != '%') {
            if (*s != *f) break;
            s++;
            continue;
        }
        f++;
        char *end;
        if (*f == 's') {
            while (isspace(*s)) s++;
            char *out = va_arg(args, char *);
            if (!*s) break;
            while (*s && !isspace(*s)) *out++ = *s++;
            *out = 0;
            assigned++;
            continue;
        }
        int base = *f == 'd' ? 10 : *f == 'x' ? 16 : *f == 'o' ? 8 : *f == 'i' ? 0 : -1;
        if (base < 0) break;
        while (isspace(*s)) s++;
        long value = strtol(s, &end, base);
        if (end == s) break;
        *va_arg(args, int *) = (int)value;
        s = end;
        assigned++;
    }
    va_end(args);
    return assigned;
}
