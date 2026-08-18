#!/usr/bin/env python3
"""analyze.py — the name-analysis engine (pure Python, no bpy).

Given a list of object records ({name, data_users, ...}) it derives, entirely from
the data (no project hardcoding):
  - cleaned grouping keys (noise stripped per editable ignore rules)
  - facet code chips (UPPERCASE_ prefixes)
  - sticky compound chips (statistical collocation)
  - category chips (leading words)
and provides the substring matching the UI uses to build Venn/union lists.

Ignore rules use simple wildcards:  #  = one digit,  *  = any run of chars.
Default rules strip Revit ids, Blender .NNN dup tags, 7-hex hashes, ' Geometry'.
"""
import re
from collections import Counter, defaultdict

DEFAULT_IGNORE = [
    r"\[\d+\]",          # [5114268] revit element id
    r"_\[\d+\]",         # _[5768506] second host id
    r"\.\d{3}\b",        # .001 blender dup tag
    r"_[0-9a-f]{7}\b",   # _6c365d4 name hash
    r"\sGeometry\b",     # trailing ' Geometry' on datablocks
]

def wildcard_to_regex(pat):
    """Turn a user pattern (with # and *) into a regex. If it already looks like a
    regex (contains \\ [ ] ( )), use it verbatim so power users can pass raw regex."""
    if any(c in pat for c in "\\[]()"):
        return pat
    esc = re.escape(pat)
    esc = esc.replace(r"\#", r"\d").replace(r"\*", r".*?")
    return esc

def clean_name(name, ignore_regexes):
    s = name
    for rx in ignore_regexes:
        s = re.sub(rx, "", s)
    s = re.sub(r"\s+", " ", s).strip(" _-")
    return s

# split on space, underscore, slash, and dash-between-letter-and-uppercase
_TOK = re.compile(r"[\s_/]+|(?<=[A-Za-z])-(?=[A-Z])")
def tokenize(name):
    return [t for t in (p.strip() for p in _TOK.split(name)) if t and t not in ("x", "-")]

def analyze(records, ignore_rules=None, min_group=1):
    """records: list of dicts with at least 'name'; optional 'data_users','count'.
    Returns a dict the UI consumes."""
    if ignore_rules is None:
        ignore_rules = DEFAULT_IGNORE
    ignore_regexes = []
    for r in ignore_rules:
        try:
            ignore_regexes.append(re.compile(wildcard_to_regex(r)))
        except re.error:
            continue  # skip a malformed rule rather than crash
    ignore_regexes = [rx.pattern for rx in ignore_regexes]

    # cleaned grouping keys
    key_counts = Counter()
    key_names = defaultdict(list)          # cleaned key -> [raw object names] for plan resolution
    for rec in records:
        nm = rec["name"]
        key = clean_name(nm, ignore_regexes)
        if not key:
            key = nm
        key_counts[key] += 1
        key_names[key].append(nm)

    groups = [{"name": k, "count": c, "names": key_names[k]} for k, c in key_counts.most_common()]
    total = sum(key_counts.values())

    # facet codes: UPPERCASE_ prefixes, weighted by object count
    facet = Counter()
    for k, c in key_counts.items():
        for m in set(re.findall(r"\b([A-Z]{1,6})_", k)):
            facet[m] += c
    facets = [{"t": f"{m}_", "n": n} for m, n in facet.most_common(24)]

    # category chips: leading token, weighted
    cat = Counter()
    for k, c in key_counts.items():
        toks = tokenize(k)
        if toks:
            cat[toks[0]] += c
    cats = [{"t": t, "n": n} for t, n in cat.most_common(12)]

    # sticky compounds via collocation (Mikolov-style phrase score)
    uni = Counter(); big = Counter(); N = 0
    for k, c in key_counts.items():
        toks = tokenize(k)
        # keep the glue so we can rebuild the real compound string
        parts = re.split(r"([\s_/-])", k)
        flat = [p for p in parts if p != ""]
        seq, seps = [], []
        for idx, p in enumerate(flat):
            if p in (" ", "_", "/", "-"):
                continue
            seq.append(p)
            nxt = flat[idx+1] if idx+1 < len(flat) else ""
            seps.append(nxt if nxt in (" ", "_", "/", "-") else " ")
        for t in seq:
            uni[t] += c; N += c
        for i in range(len(seq)-1):
            big[(seq[i], seps[i], seq[i+1])] += c
    # PMI is scale-invariant (log2 of how much more often a,b co-occur than chance);
    # only the frequency floor scales with dataset size. Rank surviving pairs by count
    # so the common, meaningful compounds (Door Shaker, Window Surrounds) come first
    # rather than rare exclusive pairs.
    import math
    min_cab = max(4, round(total * 0.001))
    min_pmi = 2.0
    # a token is "dimension noise" if it's a bare number or a lone dimension letter;
    # compounds made only of those (W x, H x, 24 D) aren't useful grouping handles
    def _noise(t):
        return bool(re.fullmatch(r"\d+([./]\d+)?", t)) or t in ("W", "H", "D", "L", "x", "X", "Ø")
    comps = []
    for (a, g, b), cab in big.items():
        if cab < min_cab:
            continue
        if _noise(a) or _noise(b):
            continue
        pmi = math.log2((cab * N) / (uni[a] * uni[b])) if uni[a] and uni[b] else 0
        if pmi < min_pmi:
            continue
        comps.append((cab, pmi, f"{a}{g}{b}"))
    comps.sort(reverse=True)  # by count desc
    seen = set(); compounds = []
    for cab, pmi, comp in comps:
        if comp in seen:
            continue
        seen.add(comp)
        compounds.append({"t": comp, "n": cab})
        if len(compounds) >= 24:
            break

    singletons = sum(1 for c in key_counts.values() if c == 1)
    return {
        "total": total,
        "unique": len(key_counts),
        "singletons": singletons,
        "groups": groups,
        "facets": facets,
        "cats": cats,
        "compounds": compounds,
    }

def resolve(term, groups, gone=None):
    """Objects (name-groups) still in the pool whose key contains term (case-insensitive)."""
    gone = gone or set()
    q = term.lower()
    return [g for g in groups if g["name"] not in gone and q in g["name"].lower()]

if __name__ == "__main__":
    import json, sys
    data = json.load(open(sys.argv[1]))
    recs = data if isinstance(data, list) else data.get("objects", [])
    out = analyze(recs)
    slim = {k: (v if k not in ("groups",) else [{kk: gg[kk] for kk in ("name", "count")} for gg in v][:5])
            for k, v in out.items()}
    print(json.dumps(slim, indent=2)[:1500])
