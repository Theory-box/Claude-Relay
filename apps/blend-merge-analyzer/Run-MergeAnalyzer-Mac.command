#!/bin/bash
# One-click launcher for macOS (no build needed). Requires Python 3.9+.
# Double-click in Finder to start. (You may need: right-click > Open, the first time.)
cd "$(dirname "$0")"
echo "Checking Python and dependencies..."
python3 -m pip install --quiet pywebview pyobjc zstandard 2>/dev/null
python3 backend/relay_app.py || {
  echo
  echo "Could not start. Make sure Python 3.9+ is installed:  https://www.python.org/downloads/"
  read -n 1 -s -r -p "Press any key to close."
}
