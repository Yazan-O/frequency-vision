import sys

import cv2 as cv
import numpy as np

ts = np.array([[1_700_000_000_000_001, 1_700_000_000_000_050, 5_000_000_000_000]], np.int64)
print("opencv", cv.__version__, "numpy", np.__version__, "python", sys.version.split()[0])
print("input int64        ", ts.ravel().tolist())
print("cv.minMaxLoc       ", cv.minMaxLoc(ts)[:2], "expected", (float(ts.min()), float(ts.max())))
print("cv.sort            ", cv.sort(ts, cv.SORT_EVERY_ROW | cv.SORT_ASCENDING).ravel().tolist())
print("cv.add CV_64S      ", cv.add(ts, ts, dtype=cv.CV_64S).ravel().tolist(), "expected", (2 * ts).ravel().tolist())
print("int32 of low word  ", ts.astype(np.int32).ravel().tolist())
ok = cv.minMaxLoc(ts.astype(np.float64))[:2] == (float(ts.min()), float(ts.max()))
bad = cv.minMaxLoc(ts)[:2] != (float(ts.min()), float(ts.max()))
print("float64 workaround correct:", ok, "| int64 input silently wrong:", bad)
sys.exit(0 if bad else 1)
