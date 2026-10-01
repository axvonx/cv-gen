/* Minimal stdio for the DOOM machine: console output and a read-only WAD. */
#ifndef _STDIO_H
#define _STDIO_H
#include <stdarg.h>
#include <stddef.h>

typedef struct FILE FILE;
extern FILE *stdin, *stdout, *stderr;
#define EOF (-1)
#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2

FILE *fopen(const char *path, const char *mode);
int fclose(FILE *f);
size_t fread(void *buffer, size_t size, size_t count, FILE *f);
size_t fwrite(const void *buffer, size_t size, size_t count, FILE *f);
int fseek(FILE *f, long offset, int whence);
long ftell(FILE *f);
int fflush(FILE *f);
int remove(const char *path);
int rename(const char *from, const char *to);
int putchar(int c);
int puts(const char *s);
int printf(const char *format, ...);
int fprintf(FILE *f, const char *format, ...);
int vfprintf(FILE *f, const char *format, va_list args);
int sprintf(char *buffer, const char *format, ...);
int snprintf(char *buffer, size_t size, const char *format, ...);
int vsnprintf(char *buffer, size_t size, const char *format, va_list args);
int sscanf(const char *s, const char *format, ...);
#endif
