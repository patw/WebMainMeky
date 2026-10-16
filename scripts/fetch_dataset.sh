#!/usr/bin/env bash
# Download the WebMainBench 545-sample subset used by the eval scripts.
# Apache-2.0, (c) opendatalab. ~109 MB.
set -euo pipefail
DEST="${1:-data}"
mkdir -p "$DEST"
URL="https://huggingface.co/datasets/opendatalab/WebMainBench/resolve/main/WebMainBench_545.jsonl"
echo "downloading WebMainBench_545.jsonl -> $DEST/"
curl -sL -o "$DEST/WebMainBench_545.jsonl" "$URL"
ls -la "$DEST/WebMainBench_545.jsonl"
echo "then: .venv/bin/python scripts/cv_wmb.py --path $DEST/WebMainBench_545.jsonl --limit 250 --folds 5"
