#!/usr/bin/env bash
# Launch the IDC Lab Assistant locally.
# Double-click in Finder (Mac) or run `./run.sh` from a terminal.

set -e

cd "$(dirname "$0")"

if ! command -v streamlit >/dev/null 2>&1; then
  echo "Streamlit not found. Installing dependencies..."
  python3 -m pip install -r requirements.txt
fi

# Streamlit opens the browser to http://localhost:8501 on first boot.
streamlit run app.py
