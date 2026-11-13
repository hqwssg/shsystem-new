#!/bin/sh
set -eu

INPUT=${1:-/tmp/carbon-render-smoke.json}
OUTPUT_DIR=${2:-/tmp}
if [ -r /etc/carbon-integration.env ]; then
  . /etc/carbon-integration.env
fi
PYTHON_BIN=${CARBON_REPORT_PYTHON:-/opt/carbon-report-venv/bin/python}
SOFFICE_BIN=${CARBON_REPORT_SOFFICE_PATH:-${REPORT_SOFFICE:-$(command -v libreoffice || command -v soffice || true)}}
DOCX="$OUTPUT_DIR/carbon-render-smoke.docx"
PDF="$OUTPUT_DIR/carbon-render-smoke.pdf"

test -f "$INPUT"
test -x "$PYTHON_BIN"
test -n "$SOFFICE_BIN"
mkdir -p "$OUTPUT_DIR"
rm -f "$DOCX" "$PDF"

export PYTHONPATH=${CARBON_REPORT_RENDERER_ROOT:-/home/ruoyi/renderer}
export PYTHONIOENCODING=utf-8
export CARBON_REPORT_SOFFICE_PATH="$SOFFICE_BIN"

"$PYTHON_BIN" -m carbon_report_agent.cli generate \
  --input "$INPUT" --output "$DOCX" --llm-enabled false
"$PYTHON_BIN" -m carbon_report_agent.cli convert-pdf \
  --input-docx "$DOCX" --output "$PDF"

test -s "$DOCX"
test -s "$PDF"
test "$(od -An -tx1 -N2 "$DOCX" | tr -d ' \n')" = '504b'
test "$(dd if="$PDF" bs=1 count=4 2>/dev/null)" = '%PDF'
echo "Report render smoke test passed: $DOCX, $PDF"
