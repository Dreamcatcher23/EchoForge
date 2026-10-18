#!/bin/bash
set -e
echo "=== EchoForge Test Suite ==="
cd "$(dirname "$0")/.."
python -m pytest tests/ -v --tb=short 2>&1
echo "=== Tests complete ==="
