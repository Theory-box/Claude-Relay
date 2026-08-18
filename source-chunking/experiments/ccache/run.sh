#!/bin/bash
# Reproduce the ccache + chunking scenarios. Requires: g++, ccache, mold.
# Usage: python3 model_gen.py && bash run.sh
set -e
export CCACHE_DIR="$PWD/.cache"
CXX="ccache g++ -O2 -std=c++17"
S(){ ccache -s | grep -iE "^[[:space:]]*(Hits|Misses):" | head -2 | sed 's/^/    /'; }

build(){ # $1=build_dir  $2..=enabled chunks
  local d="$1"; shift; local defs=""
  mkdir -p "$d"
  for c in "$@"; do u=$(echo "$c"|tr a-z A-Z); defs="$defs -DWITH_SPACE_$u"; done
  local objs=""
  for f in spine_*.cpp; do $CXX -c "$f" -o "$d/${f%.cpp}.o"; objs="$objs $d/${f%.cpp}.o"; done
  for c in "$@"; do $CXX -c "chunk_$c.cpp" -o "$d/chunk_$c.o"; objs="$objs $d/chunk_$c.o"; done
  $CXX $defs -c main.cpp -o "$d/main.o"; objs="$objs $d/main.o"
  g++ -fuse-ld=mold $objs -o "$d/app"
}

echo "### Scenario 1: cold build (console+text), empty cache"
ccache -C >/dev/null; ccache -z >/dev/null
t0=$(date +%s.%N); build build_A console text; t1=$(date +%s.%N)
echo "  wall $(echo "$t1-$t0"|bc)s  app=$(./build_A/app)"; S

echo "### Scenario 2: reconfigure (+seq) - the rebuild-often case"
ccache -z >/dev/null
t0=$(date +%s.%N); build build_B console text seq; t1=$(date +%s.%N)
echo "  wall $(echo "$t1-$t0"|bc)s  app=$(./build_B/app)"; S

echo "### Scenario 3: toggle to a different config (console+node)"
ccache -z >/dev/null
t0=$(date +%s.%N); build build_C console node; t1=$(date +%s.%N)
echo "  wall $(echo "$t1-$t0"|bc)s  app=$(./build_C/app)"; S

echo "Note: for the path-normalization and unity-alignment tests see RESULTS.md."
