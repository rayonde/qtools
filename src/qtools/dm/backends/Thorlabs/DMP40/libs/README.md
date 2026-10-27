# Windows x64 DLL placement

The user deferred obtaining the Windows SDK while developing on macOS.
**No vendor DLLs are currently bundled.** Place the real, matching-version files
from the official Thorlabs Deformable Mirror software in this directory:

```text
libs/
    TLDFM_64.dll
    TLDFMX_64.dll
    License.rtf           # preserve the vendor license from the distribution
```

The reference example loads these from:

```text
C:\Program Files\IVI Foundation\VISA\Win64\Bin
```

The qtools backend defaults to this package's `libs` directory instead; it does
not change the working directory. A custom directory can be passed as `dll_dir`.
Both DLLs must come from the same official release. Preserve the release's
license/copyright notices when including its binaries. The examples' MIT license
does not replace the SDK license.

On the Windows control computer, install the official Thorlabs software and its
VISA/USB/runtime prerequisites first. Copying the two driver DLLs alone does not
install USB drivers or guarantee that their runtime dependencies are available.
If Windows reports a missing dependency, inspect the installed SDK requirements;
do not rename unrelated DLLs to satisfy the loader.

Files placed here are package data and are included in newly built qtools wheels.
The development-only `../refs/` repositories are excluded from wheels.

Official software entry:
https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=DMP40
