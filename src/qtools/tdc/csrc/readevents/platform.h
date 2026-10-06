/* platform.h: Cross-platform compile configuration definitions. */

#ifndef PLATFORM_H
#define PLATFORM_H

#if defined(_WIN32) || defined(__WIN32__)
    #define TDC_PLATFORM_WINDOWS 1
#elif defined(__APPLE__)
    #define TDC_PLATFORM_MACOS 1
#elif defined(__linux__)
    #define TDC_PLATFORM_LINUX 1
#else
    #define TDC_PLATFORM_UNKNOWN 1
#endif

#endif /* PLATFORM_H */
