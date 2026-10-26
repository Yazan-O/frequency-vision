#!/bin/sh
set -e
cd "$(dirname "$0")"
g++ -O2 -std=c++17 -shared -fPIC -o libecf_shim.so ecf_codec.cpp ecf_shim.cpp
