#!/usr/bin/env bash
# Story 28.11: DAST scanner wrapper using nuclei.
#
# Runs nuclei against the live Docker stack with curated templates.
# Skips gracefully if nuclei is not installed.
#
# Usage:
#   API_URL=http://localhost:8001 WEB_URL=http://localhost:3001 ./run-dast.sh
#
# Environment variables:
#   API_URL   - Backend API URL (default: http://localhost:8001)
#   WEB_URL   - Web frontend URL (default: http://localhost:3001)
#   SEVERITY  - Minimum severity (default: medium,high,critical)
set -euo pipefail

API_URL="${API_URL:-http://localhost:8001}"
WEB_URL="${WEB_URL:-http://localhost:3001}"
SEVERITY="${SEVERITY:-medium,high,critical}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"

echo "=== DAST Scanner (nuclei) ==="
echo "API: ${API_URL}  |  Web: ${WEB_URL}"
echo ""

# Check if nuclei is installed
if ! command -v nuclei &>/dev/null; then
    echo "nuclei is not installed -- skipping DAST scan."
    echo "Install: go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest"
    echo ""
    echo "SKIP: nuclei not available (exit 0)"
    exit 0
fi

# Ensure results directory exists
mkdir -p "${RESULTS_DIR}"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTPUT_FILE="${RESULTS_DIR}/nuclei-${TIMESTAMP}.json"

echo "Running nuclei scan (severity: ${SEVERITY}) ..."
echo ""

# Build target list
TARGETS_FILE=$(mktemp)
trap 'rm -f "${TARGETS_FILE}"' EXIT
echo "${API_URL}" >> "${TARGETS_FILE}"
echo "${WEB_URL}" >> "${TARGETS_FILE}"

# Run nuclei with curated templates, capturing its exit code
NUCLEI_EXIT=0
nuclei \
    -l "${TARGETS_FILE}" \
    -t http/misconfiguration/ \
    -t http/exposures/ \
    -t http/vulnerabilities/ \
    -exclude-templates http/fuzzing/ \
    -exclude-templates http/takeovers/ \
    -severity "${SEVERITY}" \
    -json-export "${OUTPUT_FILE}" \
    -silent \
    -no-color \
    -timeout 10 \
    -retries 1 \
    -rate-limit 50 \
    || NUCLEI_EXIT=$?

# Clean up temp file
rm -f "${TARGETS_FILE}"

echo ""

# Count findings by severity
if [ -f "${OUTPUT_FILE}" ] && [ -s "${OUTPUT_FILE}" ]; then
    TOTAL=$(wc -l < "${OUTPUT_FILE}")
    HIGH_CRIT=$(grep -cE '"severity":"(high|critical)"' "${OUTPUT_FILE}" || true)

    echo "Results saved to: ${OUTPUT_FILE}"
    echo "Total findings: ${TOTAL}"
    echo "High/Critical: ${HIGH_CRIT}"

    if [ "${HIGH_CRIT}" -gt 0 ]; then
        echo ""
        echo "FAIL: High/critical findings detected"
        echo "Review: cat ${OUTPUT_FILE} | python3 -m json.tool"
        exit 1
    fi
else
    if [ "${NUCLEI_EXIT}" -ne 0 ]; then
        echo "FAIL: nuclei execution failed (exit ${NUCLEI_EXIT}) with no results"
        exit 1
    fi
    echo "No findings (clean scan)"
fi

echo ""
echo "PASS: No high/critical findings"
exit 0
