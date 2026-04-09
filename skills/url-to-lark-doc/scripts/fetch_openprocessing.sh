#!/bin/bash
# Fetch OpenProcessing sketch metadata and code
# Usage: fetch_openprocessing.sh <sketch_id> [output_dir]
# Output: metadata.json and code.json in output_dir

set -euo pipefail

SKETCH_ID="$1"
OUTPUT_DIR="${2:-.}"

mkdir -p "$OUTPUT_DIR"

echo "Fetching metadata for sketch $SKETCH_ID..."
curl -sL "https://openprocessing.org/api/sketch/$SKETCH_ID" \
  -H "User-Agent: Mozilla/5.0" \
  -o "$OUTPUT_DIR/metadata.json"

echo "Fetching code for sketch $SKETCH_ID..."
curl -sL "https://openprocessing.org/api/sketch/$SKETCH_ID/code" \
  -H "User-Agent: Mozilla/5.0" \
  -o "$OUTPUT_DIR/code.json"

echo "Done. Files saved to $OUTPUT_DIR/"
echo "  metadata.json - Title, description, engine, license"
echo "  code.json     - Full source code (JSON array)"
