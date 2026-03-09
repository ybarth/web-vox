#!/usr/bin/env bash
# Serve the SDK test workbench on port 5240
DIR="$(cd "$(dirname "$0")" && pwd)"
echo "SDK Test Workbench → http://localhost:5400"
python3 -m http.server 5400 --directory "$DIR"
