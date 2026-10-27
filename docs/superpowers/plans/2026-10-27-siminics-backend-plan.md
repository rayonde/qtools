# Siminics Backend Implementation Plan

1. Copy the vendor Win64 DLL, import library, and header into `backends/siminics/libs/win64`; add package exports and registry import.
2. Add immutable vendor result/event models and a pure Python T2/T3 parser with overflow and Marker decoding.
3. Add a lazy ctypes SDK wrapper with typed prototypes, error translation, device metadata, task lifecycle, and memory block cleanup.
4. Implement `SiminicsBackend` generic methods: connect/disconnect, device discovery, singles, timestamps, threshold, and software/hardware coincidence.
5. Implement Siminics extensions for T1 histogram, ITTR-T/ITTR-M raw acquisition, Marker/event access, and device timing/input configuration.
6. Add README usage and Windows deployment notes, including the distinction between `ITTR-T=6` and `ITTR-M=7`.
7. Add hardware-free parser, fake-SDK, registration, and dependency-layout tests; run targeted tests and static compilation on the active package.

The implementation will not load the Windows DLL at import time, will leave existing refs unchanged, and will preserve the user's unrelated working-tree changes.
