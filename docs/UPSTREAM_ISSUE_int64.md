<!-- DRAFT for github.com/opencv/opencv/issues. Not posted. The team posts it by hand after review. -->

# Python bindings: NumPy int64 arrays are silently truncated to int32 (5.0.0)

### System Information

- OpenCV version: 5.0.0 (`opencv-contrib-python-headless==5.0.0.93` from PyPI)
- Operating system: Windows 11 x64
- Python: 3.13.5
- NumPy: 2.4.6

### Detailed description

OpenCV 5 adds 64-bit integer Mats (`CV_64S`). In the 5.0.0 Python wheel, a NumPy `int64` array passed to any function is converted to a 32-bit integer Mat by keeping the low 32 bits of each element. There is no error and no warning. The result is silently wrong for any value outside the int32 range.

This bites any code that passes timestamps, IDs or counters stored as int64, for example event-camera timestamps in microseconds since an epoch.

Observed behaviour:

- `cv.minMaxLoc` on `[1700000000000001, 1700000000000050, 5000000000000]` returns `(404635649.0, 658067456.0)` instead of `(5000000000000.0, 1700000000000050.0)`. These are exactly the low 32 bits of the inputs.
- `cv.sort` and `cv.copyMakeBorder` return an `int32` array of the low 32 bits.
- `cv.add(a, a, dtype=cv.CV_64S)` returns an `int64` array, but of the doubled low words (`[809271298, 809271396, 1316134912]` instead of `[3400000000000002, 3400000000000100, 10000000000000]`), so the input is truncated before the operation runs.
- Wrapping the array first with `cv.Mat(a)` does not help: `np.asarray(cv.Mat(a))` is still int64, but `cv.minMaxLoc(cv.Mat(a))` gives the same wrong result.
- Small int64 values work (`cv.minMaxLoc(np.array([[1, 2, 3]], np.int64))` gives `(1.0, 3.0)`), which hides the problem in most tests.

Expected behaviour: either the int64 array becomes a `CV_64S` Mat and the result is correct, or the call raises an error when values do not fit in int32. Silent truncation is the one outcome that should not happen.

Workaround we use: convert to `float64` (exact up to 2^53) or subtract a base value and pass relative int32 values.

### Steps to reproduce

```python
import cv2 as cv
import numpy as np

ts = np.array([[1_700_000_000_000_001, 1_700_000_000_000_050, 5_000_000_000_000]], np.int64)
print(cv.__version__, np.__version__)
print("minMaxLoc       ", cv.minMaxLoc(ts)[:2], "expected", (float(ts.min()), float(ts.max())))
print("sort            ", cv.sort(ts, cv.SORT_EVERY_ROW | cv.SORT_ASCENDING))
print("add CV_64S      ", cv.add(ts, ts, dtype=cv.CV_64S), "expected", 2 * ts)
print("low 32 bits     ", ts.astype(np.int32))
print("float64 correct ", cv.minMaxLoc(ts.astype(np.float64))[:2])
```

Output:

```
5.0.0 2.4.6
minMaxLoc        (404635649.0, 658067456.0) expected (5000000000000.0, 1700000000000050.0)
sort             [[404635649 404635698 658067456]]
add CV_64S       [[ 809271298  809271396 1316134912]] expected [[3400000000000002 3400000000000100   10000000000000]]
low 32 bits      [[404635649 404635698 658067456]]
float64 correct  (5000000000000.0, 1700000000000050.0)
```

A self-contained script with an exit code (0 when the defect is present) is in our project at `tools/int64_repro.py`.

### Issue submission checklist

- [x] I report the issue, it's not a question
- [x] I checked the problem with documentation, FAQ, open issues, forum.opencv.org, Stack Overflow, etc and have not found any solution
- [ ] I updated to the latest OpenCV version and the issue is still there <!-- check against the newest 5.x wheel before posting -->
- [x] There is reproducer code and related data files (videos, images, onnx, etc)
