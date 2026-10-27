# OpenCV op benchmark: COOL and pip OpenCV 5 on Graviton, pip on x86

Written by `python bench/table.py bench/results/cool-graviton4-*.json bench/results/pip-*.json`.

| run | instance | arch | cv2 | op | threads | p50 ms | p95 ms | per s | CPU % | USD per 1M |
|---|---|---|---|---|---|---|---|---|---|---|
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | resize | 1 | 1.260 | 1.277 | 792.7 | 25 | 0.056 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | cvtColor | 1 | 0.274 | 0.287 | 3606.4 | 23 | 0.012 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | GaussianBlur | 1 | 0.636 | 0.649 | 1572.3 | 26 | 0.028 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | dft | 1 | 1.234 | 1.251 | 809.1 | 25 | 0.055 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | connectedComponentsWithStats | 1 | 2.923 | 2.934 | 342.0 | 25 | 0.130 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | dnn_forward | 1 | 800.637 | 802.739 | 1.2 | 25 | 35.494 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | resize | 4 | 0.450 | 0.462 | 2216.3 | 100 | 0.020 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | cvtColor | 4 | 0.081 | 0.086 | 12316.4 | 92 | 0.004 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | GaussianBlur | 4 | 0.205 | 0.232 | 4846.0 | 97 | 0.009 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | dft | 4 | 0.940 | 0.954 | 1063.2 | 58 | 0.042 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | connectedComponentsWithStats | 4 | 0.765 | 0.776 | 1306.9 | 100 | 0.034 |
| cool-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.1.0-dev COOL | dnn_forward | 4 | 254.804 | 255.843 | 3.9 | 100 | 11.299 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | resize | 1 | 2.611 | 2.648 | 382.4 | 50 | 0.012 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | cvtColor | 1 | 0.553 | 0.564 | 1815.0 | 50 | 0.003 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | GaussianBlur | 1 | 3.745 | 4.005 | 265.1 | 50 | 0.018 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | dft | 1 | 3.269 | 3.331 | 304.7 | 50 | 0.015 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | connectedComponentsWithStats | 1 | 4.740 | 4.804 | 210.6 | 50 | 0.022 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | dnn_forward | 1 | 1572.064 | 1600.720 | 0.6 | 50 | 7.343 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | resize | 2 | 1.308 | 1.373 | 759.9 | 101 | 0.006 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | cvtColor | 2 | 0.278 | 0.301 | 3542.5 | 97 | 0.001 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | GaussianBlur | 2 | 1.904 | 2.045 | 520.2 | 101 | 0.009 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | dft | 2 | 3.248 | 3.319 | 307.0 | 50 | 0.015 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | connectedComponentsWithStats | 2 | 2.544 | 2.654 | 390.9 | 101 | 0.012 |
| pip-graviton2-t4g.small-endpoint | t4g.small | aarch64 | 5.0.0 pip | dnn_forward | 2 | 4319.222 | 4422.412 | 0.2 | 96 | 20.252 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | resize | 1 | 1.050 | 1.065 | 951.2 | 25 | 0.047 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | cvtColor | 1 | 0.277 | 0.290 | 3566.2 | 27 | 0.012 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | GaussianBlur | 1 | 1.482 | 1.509 | 673.7 | 25 | 0.066 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | dft | 1 | 1.434 | 1.452 | 696.7 | 24 | 0.064 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | connectedComponentsWithStats | 1 | 2.991 | 3.007 | 334.5 | 25 | 0.132 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | dnn_forward | 1 | 758.285 | 762.262 | 1.3 | 25 | 33.623 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | resize | 4 | 0.393 | 0.409 | 2540.5 | 98 | 0.017 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | cvtColor | 4 | 0.080 | 0.085 | 12369.4 | 93 | 0.004 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | GaussianBlur | 4 | 0.388 | 0.401 | 2579.6 | 100 | 0.017 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | dft | 4 | 1.450 | 1.468 | 691.7 | 25 | 0.064 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | connectedComponentsWithStats | 4 | 0.895 | 0.908 | 1116.1 | 100 | 0.040 |
| pip-graviton4-c8g.xlarge-samehost | c8g.xlarge | aarch64 | 5.0.0 pip | dnn_forward | 4 | 234.055 | 234.935 | 4.3 | 100 | 10.376 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | resize | 1 | 1.038 | 1.045 | 962.2 | 25 | 0.046 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | cvtColor | 1 | 0.272 | 0.283 | 3643.6 | 27 | 0.012 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | GaussianBlur | 1 | 1.552 | 1.586 | 647.4 | 25 | 0.068 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | dft | 1 | 1.438 | 1.463 | 696.5 | 24 | 0.064 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | connectedComponentsWithStats | 1 | 2.979 | 2.998 | 335.5 | 25 | 0.132 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | dnn_forward | 1 | 749.665 | 751.325 | 1.3 | 25 | 33.212 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | resize | 4 | 0.392 | 0.409 | 2540.5 | 98 | 0.017 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | cvtColor | 4 | 0.080 | 0.085 | 12410.7 | 109 | 0.004 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | GaussianBlur | 4 | 0.398 | 0.723 | 2351.0 | 94 | 0.019 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | dft | 4 | 1.431 | 1.450 | 698.8 | 25 | 0.063 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | connectedComponentsWithStats | 4 | 0.897 | 0.910 | 1109.0 | 100 | 0.040 |
| pip-graviton4-c8g.xlarge | c8g.xlarge | aarch64 | 5.0.0 pip | dnn_forward | 4 | 233.110 | 234.322 | 4.3 | 100 | 10.343 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | resize | 1 | 0.660 | 0.686 | 1505.7 | 24 | 0.033 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | cvtColor | 1 | 0.325 | 0.340 | 3085.5 | 23 | 0.016 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | GaussianBlur | 1 | 1.093 | 1.117 | 912.6 | 25 | 0.054 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | dft | 1 | 2.088 | 2.117 | 478.5 | 25 | 0.104 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | connectedComponentsWithStats | 1 | 4.418 | 4.454 | 226.4 | 25 | 0.219 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | dnn_forward | 1 | 395.093 | 397.182 | 2.5 | 25 | 19.592 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | resize | 4 | 0.423 | 0.445 | 2362.9 | 97 | 0.021 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | cvtColor | 4 | 0.165 | 0.182 | 6051.8 | 106 | 0.008 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | GaussianBlur | 4 | 0.512 | 0.531 | 1950.6 | 100 | 0.025 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | dft | 4 | 2.079 | 2.107 | 480.6 | 25 | 0.103 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | connectedComponentsWithStats | 4 | 1.834 | 1.869 | 544.2 | 100 | 0.091 |
| pip-x86-c7i.xlarge | c7i.xlarge | x86_64 | 5.0.0 pip | dnn_forward | 4 | 198.154 | 199.112 | 5.0 | 99 | 9.821 |
