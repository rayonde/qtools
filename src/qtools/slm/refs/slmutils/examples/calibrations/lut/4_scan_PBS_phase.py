# Run: python -m slmutils.display.server
import time

import numpy as np
from tqdm import tqdm, trange

from physicsutils.devices.lbtek_opm_windows import LBTEK_OPM
from slmutils.display.client import display
from slmutils.generate import DEFAULT_DISPLAYMASK as mask

pm = LBTEK_OPM("./LBTEK_OPM_DLL")
with pm:
    # Create dict
    data = [[] for _ in range(256)]
    for _ in range(10):
        pbar = tqdm(list(range(256)))
        for level in pbar:
            display.load(mask.flat(level).array)
            time.sleep(0.05)
            power = pm.power
            data[level].append(power)
            pbar.set_description(f"{level: 3d} {power*1e6:.1f}uW")

results = [(np.mean(lst), np.std(lst, ddof=1)) for lst in data]
results = np.array(results, dtype=np.float64)
np.savetxt("scan.txt", results)
