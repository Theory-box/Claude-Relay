#!/usr/bin/env python3
"""
model_gen.py - Generate a controlled model of Blender's build structure to
measure how ccache + chunking behave. The model mirrors the one property that
dominates Blender's compile time: a large shared header (core.h, standing in for
the DNA_/BKE_ headers that ~2000 TUs each include) pulled in by every file.

  spine_NN.cpp  x20  : irreducible core files (each #includes core.h)
  chunk_<name>.cpp   : toggleable "editors"
  main.cpp           : gates chunks via -DWITH_SPACE_<NAME>, like ED_spacetypes_init()

Run this, then use run.sh to reproduce the scenarios in RESULTS.md.
"""
import glob

CHUNKS = ["console", "text", "seq", "node", "clip"]

with open("core.h", "w") as f:
    f.write("#pragma once\n")
    for h in ["vector", "map", "string", "unordered_map",
              "algorithm", "functional", "memory", "numeric"]:
        f.write(f"#include <{h}>\n")
    for i in range(1, 401):
        f.write(f"template<typename T> struct Core{i} {{ T v; std::vector<T> data;\n")
        f.write("  T sum() const { T r{}; for (auto&x:data) r+=x; return r; }\n")
        f.write("  std::map<int,T> idx; void put(int k,T x){ idx[k]=x; data.push_back(x);} };\n")

for i in range(20):
    with open(f"spine_{i:02d}.cpp", "w") as f:
        f.write('#include "core.h"\n')
        f.write(f"int spine_fn_{i:02d}(int a){{ Core1<int> c; c.put(a,a*2); return (int)c.sum()+{i}; }}\n")

for n in CHUNKS:
    with open(f"chunk_{n}.cpp", "w") as f:
        f.write('#include "core.h"\n')
        f.write(f"int chunk_{n}_register(){{ Core2<int> c; c.put(1,7); return (int)c.sum(); }}\n")

with open("main.cpp", "w") as f:
    f.write('#include <cstdio>\n')
    for i in range(20):
        f.write(f"int spine_fn_{i:02d}(int);\n")
    for n in CHUNKS:
        f.write(f"int chunk_{n}_register();\n")
    f.write("int main(){ int t=0;\n")
    for i in range(20):
        f.write(f"  t+=spine_fn_{i:02d}({i});\n")
    for n in CHUNKS:
        f.write(f"#ifdef WITH_SPACE_{n.upper()}\n  t+=chunk_{n}_register();\n#endif\n")
    f.write('  std::printf("%d\\n",t); return 0; }\n')

print(f"generated: core.h + {len(glob.glob('*.cpp'))} cpp files (spine=20, chunks={len(CHUNKS)})")
