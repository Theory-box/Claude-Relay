"""
tpage_combine.py — Combined texture page builder for OpenGOAL custom levels.

Solves the 10MB level heap limit when mixing enemies from multiple source levels.
Each source vis-pris tpage is 1-3MB; this module replaces them all with a single
skeleton tpage (~1KB) and a remap table so the PC renderer still gets correct textures.

Pipeline:
  1. Collect enemy etype list from Blender scene
  2. TpageCombiner.build() → reads tex-info.min.json, generates all outputs
  3. write_skeleton_tpage_go() → skeleton tpage-NNNN.go (no pixel data)
  4. write_dir_tpages_go() → rebuilds global dir-tpages.go with new ID included
  5. Level JSON gains: "tpages":[combined_id], "custom_tex_remap":[...], "textures":[...]

Requires ~20-line patch to goalc/build_level/jak1/build_level.cpp for custom_tex_remap.
See scratch/build_level_patch.diff in the Claude-Relay repo.

All source knowledge in knowledge-base/opengoal/tpage-system.md.
"""

import struct
import json
from pathlib import Path
from collections import defaultdict, Counter

# Jak1 TX_PAGE_VERSION (from common/versions/versions.h)
_JAK1_TX_PAGE_VERSION = 7

# Starting ID for combined tpages (safe — all IDs above 1609 are free)
COMBINED_TPAGE_BASE_ID = 1610


# ─────────────────────────────────────────────────────────────────────────────
# DataObjectGenerator
# Python port of goalc/data_compiler/DataObjectGenerator.cpp
# Writes GOAL v4 object (.go) files used by tpages and dir-tpages.
# ─────────────────────────────────────────────────────────────────────────────

class _DataObjectGenerator:
    def __init__(self):
        self._words = []
        self._ptr_links = []
        self._string_pool = {}
        self._type_links = {}
        self._symbol_links = {}

    def add_word(self, val=0):
        idx = len(self._words)
        self._words.append(int(val) & 0xFFFFFFFF)
        return idx

    def set_word(self, idx, val):
        self._words[idx] = int(val) & 0xFFFFFFFF

    def link_word_to_byte(self, source_word, target_byte):
        self._ptr_links.append((source_word, target_byte))

    def link_word_to_word(self, source, target, offset=0):
        self.link_word_to_byte(source, target * 4 + offset)

    def add_ref_to_string(self, s):
        idx = self.add_word(0)
        self._string_pool.setdefault(s, []).append(idx)
        return idx

    def add_type_tag(self, s):
        idx = self.add_word(0)
        self._type_links.setdefault(s, []).append(idx)
        return idx

    def add_symbol_link(self, s):
        idx = self.add_word(0)
        self._symbol_links.setdefault(s, []).append(idx)
        return idx

    def align(self, n_words):
        while len(self._words) % n_words:
            self._words.append(0)

    def words(self):
        return len(self._words)

    def _push_varlen(self, val, buf):
        while val > 255:
            buf.append(255)
            val -= 255
        if val == 255:
            buf.append(255)
            buf.append(0)
        else:
            buf.append(val)

    def _push_better_varlen(self, val, buf):
        if val > 0xFFFFFF:
            buf += [(val & 0xFF) | 3, (val >> 8) & 0xFF, (val >> 16) & 0xFF, (val >> 24) & 0xFF]
        elif val > 0xFFFF:
            buf += [(val & 0xFF) | 2, (val >> 8) & 0xFF, (val >> 16) & 0xFF]
        elif val > 0xFF:
            buf += [(val & 0xFF) | 1, (val >> 8) & 0xFF]
        else:
            buf.append(val & 0xFF)

    def _add_strings(self):
        for s, refs in self._string_pool.items():
            self.align(4)
            self.add_type_tag('string')
            tw = self.add_word(len(s))
            sb = list(s.encode('ascii')) + [0]
            while len(sb) % 4:
                sb.append(0)
            for i in range(len(sb) // 4):
                self.add_word(struct.unpack('<I', bytes(sb[i*4:(i+1)*4]))[0])
            for src in refs:
                self.link_word_to_word(src, tw)

    def _generate_link_table(self):
        link = []
        pl = sorted(self._ptr_links, key=lambda x: x[0])
        i = 0
        last_word = 0
        while i < len(pl):
            src, tgt = pl[i]
            diff = src - last_word
            last_word = src + 1
            self._push_varlen(diff, link)
            self._words[src] = tgt
            consecutive = 1
            while i + 1 < len(pl) and pl[i+1][0] == pl[i][0] + 1:
                self._words[pl[i+1][0]] = pl[i+1][1]
                last_word = pl[i+1][0] + 1
                consecutive += 1
                i += 1
            self._push_varlen(consecutive, link)
            i += 1
        self._push_varlen(0, link)
        for sym, refs in sorted(self._symbol_links.items()):
            for c in sym.encode('ascii'):
                link.append(c)
            link.append(0)
            prev = 0
            for x in sorted(refs):
                self._push_better_varlen((x - prev) * 4, link)
                self._words[x] = 0xFFFFFFFF
                prev = x
            link.append(0)
        for typ, refs in sorted(self._type_links.items()):
            link.append(0x80)
            for c in typ.encode('ascii'):
                link.append(c)
            link.append(0)
            prev = 0
            for x in sorted(refs):
                self._push_better_varlen((x - prev) * 4, link)
                self._words[x] = 0xFFFFFFFF
                prev = x
            link.append(0)
        self._push_varlen(0, link)
        while (len(link) + 12) % 64:
            link.append(0)
        return bytes(link)

    def generate_v4(self):
        """Serialise to GOAL v4 .go format (used by tpages and dir-tpages)."""
        self._add_strings()
        link = self._generate_link_table()
        code_size = ((len(self._words) * 4) + 15) & ~15
        link_hdr_len = 12 + len(link)
        hdr4 = struct.pack('<IIII', 0xFFFFFFFF, link_hdr_len, 4, code_size)
        obj_data = struct.pack('<' + 'I' * len(self._words), *self._words)
        padding = bytes(code_size - len(obj_data))
        hdr2 = struct.pack('<III', 0xFFFFFFFF, link_hdr_len, 2)
        return hdr4 + obj_data + padding + hdr2 + link


# ─────────────────────────────────────────────────────────────────────────────
# .go file builders
# ─────────────────────────────────────────────────────────────────────────────

def build_skeleton_tpage_go(tpage_id: int, tpage_name: str, tex_count: int) -> bytes:
    """
    Build a minimal skeleton tpage .go with no pixel data.
    All tex slots = #f. PC renderer textures served by the FR3.
    tpage_id:   new combined ID (e.g. 1610)
    tpage_name: name string embedded (e.g. 'custom-combined')
    tex_count:  number of texture slots (= total remapped textures)
    """
    gen = _DataObjectGenerator()
    gen.add_type_tag('texture-page')        # word 0
    fi_ref   = gen.add_word(0)              # word 1: → file-info
    gen.add_ref_to_string(tpage_name)       # word 2: → name
    gen.add_word(tpage_id)                  # word 3: id
    gen.add_word(tex_count)                 # word 4: length
    gen.add_word(1)                         # word 5: mip0_size (placeholder)
    gen.add_word(1)                         # word 6: size (placeholder)
    seg0_ptr = gen.add_word(0)              # word 7: seg0.block_data → pixel data
    gen.add_word(1)                         # word 8: seg0.size = 1
    gen.add_word(0)                         # word 9: seg0.dest = 0
    for _ in range(6):                      # seg1 + seg2 (all zero)
        gen.add_word(0)
    for _ in range(16):                     # pad[16]
        gen.add_word(0)
    for _ in range(tex_count):              # data[] — all #f
        gen.add_symbol_link('#f')

    gen.align(4)
    fi_start = gen.add_type_tag('file-info')
    gen.add_symbol_link('texture-page')     # file_type
    gen.add_ref_to_string(tpage_name)       # file_name
    gen.add_word(_JAK1_TX_PAGE_VERSION)     # major_version = 7
    gen.add_word(0)                         # minor_version
    gen.add_ref_to_string('Unknown')        # maya_file_name
    gen.add_ref_to_string('og-custom')      # tool_debug
    gen.add_word(0)                         # mdb_file_name

    gen.align(4)
    pix_start = gen.words()
    gen.add_word(0)                         # 4-byte dummy pixel data

    gen.link_word_to_word(fi_ref, fi_start)
    gen.link_word_to_word(seg0_ptr, pix_start)
    return gen.generate_v4()


def build_dir_tpages_go(id_to_length: dict) -> bytes:
    """
    Build dir-tpages.go — the global texture-page-dir object.
    id_to_length: {tpage_id: texture_count}. All IDs from 0 to max are covered;
    missing IDs get length 0. This replaces out/jak1/obj/dir-tpages.go.
    """
    if not id_to_length:
        raise ValueError("id_to_length must not be empty")
    max_id = max(id_to_length.keys())
    lengths = [id_to_length.get(i, 0) for i in range(max_id + 1)]
    gen = _DataObjectGenerator()
    gen.add_type_tag('texture-page-dir')
    gen.add_word(len(lengths))
    for length in lengths:
        gen.add_word(length)
        gen.add_symbol_link('#f')   # page ptr (null at load time)
        gen.add_symbol_link('#f')   # link ptr (null at load time)
    return gen.generate_v4()


# ─────────────────────────────────────────────────────────────────────────────
# tex-info loader
# ─────────────────────────────────────────────────────────────────────────────

def _find_tex_info(data_root: Path) -> Path:
    """Locate tex-info.min.json relative to the OpenGOAL data root."""
    candidates = [
        data_root / "decompiler" / "config" / "jak1" / "ntsc_v1" / "tex-info.min.json",
        data_root / "data" / "decompiler" / "config" / "jak1" / "ntsc_v1" / "tex-info.min.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"tex-info.min.json not found near {data_root}. "
        "Run the decompiler first (it extracts texture info from the game ISO)."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Enemy → texture substrings mapping
# Keys match the etype strings used in ENTITY_DEFS / ETYPE_TPAGES.
# Values are substrings found in texture names in tex-info.min.json.
# ─────────────────────────────────────────────────────────────────────────────

ENEMY_TEX_SUBSTRINGS = {
    "babak":           ["babak"],
    "lurkercrab":      ["crab-"],
    "lurkerpuppy":     ["lurkerpuppy", "lurker-puppy"],
    "lurkerworm":      ["lurkerworm", "lurker-worm", "worm-"],
    "hopper":          ["hopper"],
    "junglesnake":     ["junglesnake", "jungle-snake"],
    "kermit":          ["kermit"],
    "swamp-bat":       ["swamp-bat", "swampbat", "lurkbat"],
    "swamp-rat":       ["lurkrat", "lurker-rat", "swamp-rat"],
    "yeti":            ["yeti"],
    "snow-bunny":      ["bunny-"],
    "double-lurker":   ["toplurker", "bottomlurker"],
    "puffer":          ["puffer"],
    "bully":           ["bully"],
    "flying-lurker":   ["flying-lurker", "flyinglurker", "flylurk"],
    "baby-spider":     ["baby-spider", "babyspider", "bab-spid"],
    "mother-spider":   ["mother-spider", "motherspider", "mom-spid"],
    "gnawer":          ["gnawer"],
    "driller-lurker":  ["driller-lurker", "drillerlurker", "drlurker"],
    "cavecrusher":     ["cavecrusher"],
    "quicksandlurker": ["quicksandlurker", "qsl-"],
    "muse":            ["muse-"],
    "bonelurker":      ["bonelurker", "bone-lurker"],
    "balloonlurker":   ["balloonlurker"],
    "sharkey":         ["sharkey", "shark-"],
    "green-eco-lurker":["green-eco-lurker"],
    "plunger-lurker":  ["plunger-lurker", "plungerlurker"],
}


# ─────────────────────────────────────────────────────────────────────────────
# TpageCombineResult
# ─────────────────────────────────────────────────────────────────────────────

class TpageCombineResult:
    """All outputs from TpageCombiner.build()."""
    def __init__(self):
        self.combined_tpage_id: int = 0
        self.combined_tex_count: int = 0
        self.skeleton_go: bytes = b''
        self.dir_tpages_go: bytes = b''
        self.remap_table: list = []        # [(orig_u32, new_u32), ...] sorted
        self.level_json_fields: dict = {}  # merge into level JSON
        self.eliminated_groups: set = set()    # tpage group names removed
        self.eliminated_tpage_files: list = [] # e.g. ['tpage-659.go', ...]
        self.source_tpage_names: dict = {}     # tpage_id -> tpage_name string


# ─────────────────────────────────────────────────────────────────────────────
# TpageCombiner
# ─────────────────────────────────────────────────────────────────────────────

class TpageCombiner:
    """
    Builds all tpage combine outputs for a set of actor etypes.

    data_root: Path to the OpenGOAL data directory (the one containing goal_src/, etc.)
    """

    def __init__(self, data_root):
        self._data_root = Path(data_root)
        self._tex_info = None
        self._id_to_length = {}

    def _load_tex_info(self):
        if self._tex_info is not None:
            return
        p = _find_tex_info(self._data_root)
        raw = json.loads(p.read_text())
        self._tex_info = raw
        counts = Counter()
        for entry in raw:
            counts[entry[0] >> 16] += 1
        self._id_to_length = dict(counts)

    def get_textures_for_etypes(self, etypes: list) -> list:
        """
        Return all texture entries for the given enemy etypes.
        Each entry: {name, tpage_name, orig_page, orig_idx, orig_masked}
        Deduplicated by (page, idx).
        """
        self._load_tex_info()
        substrings = set()
        for etype in etypes:
            for s in ENEMY_TEX_SUBSTRINGS.get(etype, [etype]):
                substrings.add(s)
        if not substrings:
            return []

        seen, results = set(), []
        for entry in self._tex_info:
            combo_id = entry[0]
            tex = entry[1]
            name = tex['name']
            if any(s in name for s in substrings):
                pc_page = combo_id >> 16
                pc_idx  = combo_id & 0xFFFF
                key = (pc_page, pc_idx)
                if key not in seen:
                    seen.add(key)
                    goal_texid = (pc_page << 20) | (pc_idx << 8)
                    results.append({
                        'name':       name,
                        'tpage_name': tex['tpage_name'],
                        'orig_page':  pc_page,
                        'orig_idx':   pc_idx,
                        'orig_masked': goal_texid & 0xFFFFFF00,
                    })
        return results

    def analyse(self, etypes: list) -> dict:
        """
        Return heap analysis info for UI display without building outputs.
        {source_tpages, total_textures, pages: {id: {name, count, etypes}},
         heap_saving_mb, tpage_files_eliminated}
        """
        textures = self.get_textures_for_etypes(etypes)
        pages = {}
        for t in textures:
            pid = t['orig_page']
            if pid not in pages:
                pages[pid] = {'name': t['tpage_name'], 'count': 0, 'etypes': set()}
            pages[pid]['count'] += 1
            for etype in etypes:
                for s in ENEMY_TEX_SUBSTRINGS.get(etype, [etype]):
                    if s in t['name']:
                        pages[pid]['etypes'].add(etype)
        return {
            'source_tpages': len(pages),
            'total_textures': len(textures),
            'pages': pages,
            'heap_saving_mb': max(0, (len(pages) - 1) * 2.0),
        }

    def build(self, etypes: list, combined_tpage_id: int = COMBINED_TPAGE_BASE_ID,
              combined_name: str = 'custom-combined') -> TpageCombineResult:
        """
        Build all outputs for the given enemy etype list.

        etypes:             list of etype strings from ENTITY_DEFS, e.g. ['kermit', 'lurkercrab']
        combined_tpage_id:  ID for the new combined tpage (default 1610)
        combined_name:      name string embedded in the .go files

        Returns TpageCombineResult.
        """
        self._load_tex_info()
        textures = self.get_textures_for_etypes(etypes)
        if not textures:
            raise ValueError(f"No textures found for etypes: {etypes}")

        # Assign sequential slots in the combined tpage
        remap_table = []
        textures_json = defaultdict(list)
        for slot, t in enumerate(textures):
            new_goal = (combined_tpage_id << 20) | (slot << 8) | 0x14  # 0x14 = required flags
            remap_table.append((t['orig_masked'], new_goal))
            textures_json[t['tpage_name']].append(t['name'])

        # Sort by orig — GOAL engine binary-searches this table
        remap_table.sort(key=lambda x: x[0])

        combined_tex_count   = len(textures)
        eliminated_page_ids  = {t['orig_page'] for t in textures}
        source_tpage_names   = {t['orig_page']: t['tpage_name'] for t in textures}

        # Skeleton tpage .go
        skeleton_go = build_skeleton_tpage_go(combined_tpage_id, combined_name, combined_tex_count)

        # dir-tpages.go — include all existing IDs plus combined
        id_to_length = dict(self._id_to_length)
        id_to_length[combined_tpage_id] = combined_tex_count
        dir_go = build_dir_tpages_go(id_to_length)

        # Level JSON fields
        # custom_tex_remap: [[orig, new], ...] — consumed by patched build_level.cpp
        custom_tex_remap = [[int(orig), int(new)] for orig, new in remap_table]
        # textures: [[tpage_name, tex1, tex2, ...], ...] — selective FR3 extraction
        textures_field = [[tn] + names for tn, names in textures_json.items()]

        result = TpageCombineResult()
        result.combined_tpage_id    = combined_tpage_id
        result.combined_tex_count   = combined_tex_count
        result.skeleton_go          = skeleton_go
        result.dir_tpages_go        = dir_go
        result.remap_table          = remap_table
        result.source_tpage_names   = source_tpage_names
        result.eliminated_tpage_files = [f"tpage-{pid}.go" for pid in eliminated_page_ids]
        result.level_json_fields = {
            'tpages':          [combined_tpage_id],
            'custom_tex_remap': custom_tex_remap,
            'textures':         textures_field,
        }
        return result


# ─────────────────────────────────────────────────────────────────────────────
# File writing helpers (called from build.py)
# ─────────────────────────────────────────────────────────────────────────────

def write_tpage_combine_files(result: TpageCombineResult,
                               level_obj_dir: Path,
                               game_obj_dir: Path) -> dict:
    """
    Write skeleton tpage .go and dir-tpages.go to disk.

    level_obj_dir: <data>/custom_assets/jak1/levels/<name>/  (beside the .gd)
    game_obj_dir:  <data>/out/jak1/obj/  (where dir-tpages.go lives for GAME.DGO)

    Returns dict of written paths.
    """
    level_obj_dir = Path(level_obj_dir)
    game_obj_dir  = Path(game_obj_dir)
    level_obj_dir.mkdir(parents=True, exist_ok=True)
    game_obj_dir.mkdir(parents=True, exist_ok=True)

    tpage_filename = f"tpage-{result.combined_tpage_id}.go"
    tpage_path     = level_obj_dir / tpage_filename
    dir_path       = game_obj_dir  / "dir-tpages.go"

    tpage_path.write_bytes(result.skeleton_go)
    dir_path.write_bytes(result.dir_tpages_go)

    return {'skeleton_tpage': str(tpage_path), 'dir_tpages': str(dir_path)}


def get_unique_tpage_groups(actors: list) -> set:
    """
    Given the actor list from collect_actors(), return the set of unique
    tpage_group strings for enemy-type actors (those with a tpage_group key).
    Used to decide whether combining is needed (>1 group = yes).
    """
    from .data import ENTITY_DEFS
    groups = set()
    for a in actors:
        defn = ENTITY_DEFS.get(a.get('etype', ''), {})
        grp = defn.get('tpage_group')
        if grp:
            groups.add(grp)
    return groups


def get_enemy_etypes_from_actors(actors: list) -> list:
    """
    Extract the unique enemy etypes from the actor list that have texture data
    (i.e. appear in ENEMY_TEX_SUBSTRINGS).
    """
    seen, result = set(), []
    for a in actors:
        etype = a.get('etype', '')
        if etype in ENEMY_TEX_SUBSTRINGS and etype not in seen:
            seen.add(etype)
            result.append(etype)
    return result
