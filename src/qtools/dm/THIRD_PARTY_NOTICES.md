# References and third-party notices

The DMP40 lifecycle, relaxation loop and single-Zernike pattern workflow are
adapted from Thorlabs' `Light_Control_and_Manipulation_Examples`, specifically:

- `Python/DMP40 DMH40 Deformable Mirrors/DMP40 using ctypes - Python 3.py`
- `Matlab/DMP40 DMH40 Deformable Mirrors/Deformable_Mirrors_NET.m`

Upstream: https://github.com/Thorlabs/Light_Control_and_Manipulation_Examples

The ctypes signatures and flags are the Thorlabs `TLDFM.h`, `TLDFMX.h`,
`TLDFM_def.h` and `TLDFMX_def.h` declarations. Header declarations were checked
against the vendor headers archived in `royerlab/dmp40j/lib/dmp40`; no control
algorithm from that wrapper is incorporated. The package does not incorporate
`dmlib` or manufacture a hardware calibration matrix.

No SDK binaries are bundled at this stage. Future DLLs remain subject to their
Thorlabs SDK license; preserve the official distribution's license and notices
alongside them. The MIT license below applies to the example code, not the DLLs.

## License of the referenced example code

MIT License

Copyright (c) 2022 Thorlabs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
