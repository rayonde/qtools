# Windows x64 SDK files

This directory contains the matching 64-bit Thorlabs Deformable Mirror SDK files:

```text
TLDFM_64.dll     3.2.1880.67
TLDFMX_64.dll    3.2.1876.59
License.rtf      Thorlabs Deformable Mirror software license
```

They were copied from a local official Thorlabs installation on 2026-10-30:

```text
C:\Program Files\IVI Foundation\VISA\Win64\Bin\TLDFM_64.dll
C:\Program Files\IVI Foundation\VISA\Win64\Bin\TLDFMX_64.dll
C:\Program Files (x86)\Thorlabs\Deformable Mirror\License.rtf
```

SHA-256 fingerprints of the bundled files:

```text
TLDFM_64.dll   E7C779C5C04CDC0C9558B8A7CA227C596D839C4520B8D5FF0BDAC0EF5229D6C3
TLDFMX_64.dll  280C972E78B3D27CFE671874854E7D250210573A5B210EE2BE4139CB58351114
License.rtf    04A35A7BFBBC37BC9BBCAE36087B4922F3C08660E3759C9F6F10B6FE2E5C9778
```

The reference Python example loads these from
`C:\Program Files\IVI Foundation\VISA\Win64\Bin`. The qtools backend defaults to
this package-local directory instead and does not change the working directory.
A custom directory can be passed as `dll_dir=...`. Both DLLs must come from the
same official release.

The bundled DLLs are Windows PE/COFF x64 binaries. `TLDFM_64.dll` imports Windows
system libraries including `SETUPAPI`, `ADVAPI32`, `USER32`, and `WS2_32`;
`TLDFMX_64.dll` also depends on `TLDFM_64.dll`. They require a Windows x64 runtime.

## Runtime prerequisites

On the Windows control computer, install the official Thorlabs software and its
WinUSB/runtime prerequisites first. Copying the two driver DLLs does not install
the `WinUSB` device driver and does not guarantee that runtime dependencies are
available. If Windows reports a missing dependency, inspect the installed SDK
requirements; do not rename unrelated DLLs to satisfy the loader.

## Validation

On 2026-10-30 the bundled files were loaded by qtools on Windows 10 x64 with
64-bit Python 3.14.6. The backend found a DMP40-P01 (serial `M01325728`), opened
and closed a session, queried 40 segments / 3 tilt arms, applied a small Zernike
and tilt command, read the resulting voltages back, and restored the initial
100 V reference outputs.

Files placed here are package data and are included in newly built qtools
wheels. The development-only `../refs/` repositories are excluded from wheels.
The included `License.rtf` is the vendor license; the examples' MIT license does
not replace it. Review the vendor terms before redistributing these binaries.

Official software entry:
https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=DMP40
