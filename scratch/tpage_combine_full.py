"""
tpage_combine_full.py — Complete tpage combine pipeline for OpenGOAL custom levels.

Handles both open questions:
  Q1 (dir-tpages): Written directly in Python using DataObjectGenerator.
                   No need to touch tpage-dir.txt — we write dir-tpages.go ourselves.
  Q2 (remap table): Emitted as "custom_tex_remap" in the level JSON.
                    Requires ~20-line patch to build_level.cpp (see build_level_patch.diff).

Usage from addon's export.py:
    from .tpage_combine import TpageCombiner
    combiner = TpageCombiner(data_path)
    result = combiner.build(enemy_type_names, combined_tpage_id=1610)
    # result has: .skeleton_go_bytes, .dir_tpages_go_bytes, .level_json_fields, .remap_table
"""

import struct
import json
from pathlib import Path
from collections import defaultdict
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# DataObjectGenerator — Python port of goalc/data_compiler/DataObjectGenerator
# ─────────────────────────────────────────────────────────────────────────────

class DataObjectGenerator:
    def __init__(self):
        self._words = []
        self._ptr_links = []       # (source_word, target_byte)
        self._string_pool = {}     # str -> [word_idx]
        self._type_links = {}      # type_name -> [word_idx]
        self._symbol_links = {}    # sym_name -> [word_idx]

    def add_word(self, val=0):
        idx = len(self._words)
        self._words.append(int(val) & 0xFFFFFFFF)
        return idx

    def set_word(self, idx, val):
        self._words[idx] = int(val) & 0xFFFFFFFF

    def current_offset_bytes(self):
        return len(self._words) * 4

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

    def generate_v2(self):
        """BSP files use v2."""
        self._add_strings()
        link = self._generate_link_table()
        link_hdr_len = 12 + len(link)
        # LinkHeaderV2
        hdr = struct.pack('<III', 0xFFFFFFFF, link_hdr_len, 2)
        obj_data = struct.pack('<' + 'I' * len(self._words), *self._words)
        result = hdr + link + obj_data
        while len(result) % 16:
            result += b'\x00'
        return result

    def generate_v4(self):
        """tpage .go files use v4."""
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
# Skeleton tpage .go writer
# Writes a minimal valid tpage-NNNN.go with no pixel data.
# All texture slots are #f. Actual pixels served by FR3.
# Jak1 TX_PAGE_VERSION = 7 (versions.h)
# ─────────────────────────────────────────────────────────────────────────────

def build_skeleton_tpage_go(tpage_id: int, tpage_name: str, tex_count: int) -> bytes:
    """
    Build skeleton tpage .go bytes.
    tpage_id:   new combined tpage ID (e.g. 1610)
    tpage_name: name string embedded in file (e.g. 'custom-combined')
    tex_count:  number of texture slots (>= max remapped index + 1)
    Returns raw bytes of the .go file.
    """
    gen = DataObjectGenerator()

    # texture-page basic
    gen.add_type_tag('texture-page')        # word 0
    fi_ref   = gen.add_word(0)              # word 1: → file-info
    gen.add_ref_to_string(tpage_name)       # word 2: → name string
    gen.add_word(tpage_id)                  # word 3: id
    gen.add_word(tex_count)                 # word 4: length
    gen.add_word(1)                         # word 5: mip0_size (placeholder)
    gen.add_word(1)                         # word 6: size (placeholder)
    # segment[0]
    seg0_ptr = gen.add_word(0)              # word 7: → pixel data
    gen.add_word(1)                         # word 8: seg0.size = 1
    gen.add_word(0)                         # word 9: seg0.dest = 0
    # segment[1] and [2] — all zeros
    for _ in range(6):
        gen.add_word(0)                     # words 10-15
    # pad[16]
    for _ in range(16):
        gen.add_word(0)                     # words 16-31
    # data[tex_count] — all #f
    for _ in range(tex_count):
        gen.add_symbol_link('#f')           # words 32..32+tex_count-1

    # file-info basic
    gen.align(4)
    fi_start = gen.add_type_tag('file-info')
    gen.add_symbol_link('texture-page')     # file_type
    gen.add_ref_to_string(tpage_name)       # file_name
    gen.add_word(7)                         # major_version = Jak1 TX_PAGE_VERSION
    gen.add_word(0)                         # minor_version
    gen.add_ref_to_string('Unknown')        # maya_file_name
    gen.add_ref_to_string('og-custom')      # tool_debug
    gen.add_word(0)                         # mdb_file_name

    # minimal pixel data block (1 word)
    gen.align(4)
    pix_start = gen.words()
    gen.add_word(0)

    # fix up pointers
    gen.link_word_to_word(fi_ref, fi_start)
    gen.link_word_to_word(seg0_ptr, pix_start)

    return gen.generate_v4()


# ─────────────────────────────────────────────────────────────────────────────
# dir-tpages.go writer
# Writes the global texture-page-dir object.
# lengths: list indexed by tpage ID, value = texture count for that page.
# Gaps (unused IDs) get length 0.
# Jak1 dir has entries from ID 0 up to max_id, all in one flat array.
# ─────────────────────────────────────────────────────────────────────────────

def build_dir_tpages_go(id_to_length: dict) -> bytes:
    """
    Build dir-tpages.go bytes.
    id_to_length: dict of {tpage_id: texture_count}
    All IDs from 0 to max(id_to_length) will be in the array; missing = 0.
    Returns raw bytes.
    """
    if not id_to_length:
        raise ValueError("id_to_length must not be empty")
    max_id = max(id_to_length.keys())
    lengths = [id_to_length.get(i, 0) for i in range(max_id + 1)]

    gen = DataObjectGenerator()
    gen.add_type_tag('texture-page-dir')
    gen.add_word(len(lengths))
    for length in lengths:
        gen.add_word(length)
        gen.add_symbol_link('#f')   # page ptr (null until loaded)
        gen.add_symbol_link('#f')   # link ptr (null until loaded)

    return gen.generate_v4()


# ─────────────────────────────────────────────────────────────────────────────
# tex-info.min.json reader
# ─────────────────────────────────────────────────────────────────────────────

def load_tex_info(data_path: str) -> list:
    """
    Load tex-info.min.json from the decompiler config.
    data_path: the OpenGOAL data/ directory (contains decompiler/)
    Returns list of [combo_id, {idx, name, tpage_name}] entries.
    """
    candidates = [
        Path(data_path) / 'decompiler' / 'config' / 'jak1' / 'ntsc_v1' / 'tex-info.min.json',
        Path(data_path) / 'jak-project' / 'decompiler' / 'config' / 'jak1' / 'ntsc_v1' / 'tex-info.min.json',
    ]
    for p in candidates:
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError(f"Could not find tex-info.min.json near {data_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Remap table builder
# ─────────────────────────────────────────────────────────────────────────────

# Mapping of enemy type name (as used in addon) → texture name substrings to match.
# All textures whose name contains ANY of the substrings will be included.
ENEMY_TEXTURE_SUBSTRINGS = {
    'babak':           ['babak'],
    'hopper':          ['hopper'],
    'kermit':          ['kermit'],
    'lurker-crab':     ['crab-'],
    'snow-bunny':      ['bunny-'],
    'jungle-snake':    ['junglesnake', 'jungle-snake'],
    'dark-eco-plant':  ['darkvine'],
    'fisher':          ['fisher'],
    'lurker-shark':    ['sharkey'],
    'periscope':       ['periscope'],
    'spike-plant':     ['spike'],
    'yeti':            ['yeti'],
    'bully':           ['bully'],
    'mother-spider':   ['mothspider', 'mother-spider'],
    'green-eco-bro':   ['eco-bro'],
    'lurker-rat':      ['lurker-rat'],
    'babak-with-cannon': ['babak'],   # same textures as babak
    'lurker-crab-with-cannon': ['crab-'],
}


class TpageCombineResult:
    def __init__(self):
        self.skeleton_go_bytes: bytes = b''
        self.dir_tpages_go_bytes: bytes = b''
        self.remap_table: list = []          # [(orig_u32, new_u32), ...] sorted
        self.level_json_fields: dict = {}    # fields to merge into level JSON
        self.combined_tpage_id: int = 0
        self.combined_tex_count: int = 0
        self.eliminated_tpage_ids: set = set()
        self.source_tpage_names: dict = {}   # tpage_id -> tpage_name


class TpageCombiner:
    """
    Main entry point. Given a list of enemy type names from the addon,
    builds all the outputs needed for the combined tpage pipeline.
    """

    # Texture counts for all known game tpages (from tex-info analysis).
    # Used to build the dir-tpages.go length table for existing IDs.
    # Only enemy-relevant vis-pris pages listed here; full list from tex-info at runtime.
    KNOWN_TPAGE_LENGTHS = {}  # populated from tex-info at build time

    def __init__(self, data_path: str):
        """
        data_path: path to the OpenGOAL data directory (or jak-project root)
        """
        self.data_path = data_path
        self._tex_info = None
        self._id_to_length = {}  # tpage_id -> texture count (from tex-info)

    def _ensure_tex_info(self):
        if self._tex_info is None:
            self._tex_info = load_tex_info(self.data_path)
            # Build id_to_length from tex-info
            from collections import Counter
            counts = Counter()
            for entry in self._tex_info:
                page_id = entry[0] >> 16
                counts[page_id] += 1
            self._id_to_length = dict(counts)

    def get_textures_for_enemies(self, enemy_type_names: list) -> list:
        """
        Given a list of enemy type names (e.g. ['kermit', 'lurker-crab']),
        return all texture entries from tex-info that belong to those enemies.
        Each entry: {name, tpage_name, orig_page, orig_idx, orig_masked_goal_texid}
        Deduplicates by (page, idx).
        """
        self._ensure_tex_info()
        substrings = set()
        for enemy in enemy_type_names:
            for substr in ENEMY_TEXTURE_SUBSTRINGS.get(enemy, [enemy]):
                substrings.add(substr)

        seen = set()
        results = []
        for entry in self._tex_info:
            combo_id = entry[0]
            tex = entry[1]
            name = tex['name']
            if any(s in name for s in substrings):
                pc_page = combo_id >> 16
                pc_idx = combo_id & 0xFFFF
                key = (pc_page, pc_idx)
                if key not in seen:
                    seen.add(key)
                    goal_texid = (pc_page << 20) | (pc_idx << 8)
                    results.append({
                        'name': name,
                        'tpage_name': tex['tpage_name'],
                        'orig_page': pc_page,
                        'orig_idx': pc_idx,
                        'orig_masked': goal_texid & 0xFFFFFF00,
                    })
        return results

    def build(self, enemy_type_names: list, combined_tpage_id: int = 1610,
              combined_name: str = 'custom-combined') -> TpageCombineResult:
        """
        Build all outputs for a combined tpage covering the given enemy types.

        enemy_type_names: list of enemy type strings, e.g. ['kermit', 'lurker-crab']
        combined_tpage_id: ID for the new combined tpage (default 1610)
        combined_name: name string embedded in the .go file

        Returns TpageCombineResult with all outputs.
        """
        self._ensure_tex_info()
        textures = self.get_textures_for_enemies(enemy_type_names)

        if not textures:
            raise ValueError(f"No textures found for enemies: {enemy_type_names}")

        # Assign sequential slots in the combined tpage
        remap_table = []
        textures_json = defaultdict(list)   # tpage_name -> [tex_name]
        for slot, t in enumerate(textures):
            new_goal = (combined_tpage_id << 20) | (slot << 8) | 0x14
            remap_table.append((t['orig_masked'], new_goal))
            textures_json[t['tpage_name']].append(t['name'])

        # Sort by orig (REQUIRED — GOAL does binary search on this table)
        remap_table.sort(key=lambda x: x[0])

        combined_tex_count = len(textures)
        eliminated_ids = {t['orig_page'] for t in textures}

        # --- Build skeleton tpage .go ---
        skeleton_go = build_skeleton_tpage_go(combined_tpage_id, combined_name, combined_tex_count)

        # --- Build dir-tpages.go ---
        # Include all existing tpage IDs from tex-info PLUS our new combined ID
        id_to_length = dict(self._id_to_length)
        id_to_length[combined_tpage_id] = combined_tex_count
        dir_go = build_dir_tpages_go(id_to_length)

        # --- Level JSON fields ---
        # custom_tex_remap: [[orig, new], ...] — consumed by patched build_level.cpp
        custom_tex_remap = [[orig, new] for orig, new in remap_table]

        # textures: [[tpage_name, tex1, tex2, ...], ...] — for FR3 selective extraction
        textures_field = [[tpage_name] + names for tpage_name, names in textures_json.items()]

        level_json_fields = {
            'tpages': [combined_tpage_id],
            'custom_tex_remap': custom_tex_remap,
            'textures': textures_field,
        }

        result = TpageCombineResult()
        result.skeleton_go_bytes = skeleton_go
        result.dir_tpages_go_bytes = dir_go
        result.remap_table = remap_table
        result.level_json_fields = level_json_fields
        result.combined_tpage_id = combined_tpage_id
        result.combined_tex_count = combined_tex_count
        result.eliminated_tpage_ids = eliminated_ids
        result.source_tpage_names = {t['orig_page']: t['tpage_name'] for t in textures}
        return result

    def get_tpage_analysis(self, enemy_type_names: list) -> dict:
        """
        Analyse heap impact without building outputs.
        Returns info suitable for displaying in the addon UI.
        """
        self._ensure_tex_info()
        textures = self.get_textures_for_enemies(enemy_type_names)
        source_pages = {}
        for t in textures:
            pid = t['orig_page']
            if pid not in source_pages:
                source_pages[pid] = {'name': t['tpage_name'], 'count': 0, 'enemies': set()}
            source_pages[pid]['count'] += 1
            # find which enemy this came from
            for enemy in enemy_type_names:
                for s in ENEMY_TEXTURE_SUBSTRINGS.get(enemy, [enemy]):
                    if s in t['name']:
                        source_pages[pid]['enemies'].add(enemy)

        return {
            'source_tpages': len(source_pages),
            'total_textures': len(textures),
            'pages': source_pages,
            'heap_saving_estimate_mb': (len(source_pages) - 1) * 2.0,  # rough ~2MB per full vis-pris
        }


# ─────────────────────────────────────────────────────────────────────────────
# Addon integration helpers
# ─────────────────────────────────────────────────────────────────────────────

def write_tpage_combine_outputs(result: TpageCombineResult, level_obj_dir: str,
                                 game_out_dir: str) -> dict:
    """
    Write the skeleton tpage .go and dir-tpages.go to disk.

    level_obj_dir: e.g. <data_path>/custom_levels/my_level/obj/
    game_out_dir:  e.g. <data_path>/out/jak1/obj/   (where dir-tpages.go lives)

    Returns dict of written file paths.
    """
    level_obj = Path(level_obj_dir)
    game_out = Path(game_out_dir)
    level_obj.mkdir(parents=True, exist_ok=True)
    game_out.mkdir(parents=True, exist_ok=True)

    tpage_name = f'tpage-{result.combined_tpage_id}.go'
    tpage_path = level_obj / tpage_name
    tpage_path.write_bytes(result.skeleton_go_bytes)

    dir_path = game_out / 'dir-tpages.go'
    dir_path.write_bytes(result.dir_tpages_go_bytes)

    return {
        'skeleton_tpage': str(tpage_path),
        'dir_tpages': str(dir_path),
    }


def merge_into_level_json(level_json_path: str, fields: dict) -> None:
    """
    Merge the tpage combine fields into an existing level JSON file.
    Backs up the original.
    """
    p = Path(level_json_path)
    data = json.loads(p.read_text())
    data.update(fields)
    backup = p.with_suffix('.json.bak')
    backup.write_bytes(p.read_bytes())
    p.write_text(json.dumps(data, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# Quick self-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import tempfile, os

    print('=== Skeleton tpage writer test ===')
    data = build_skeleton_tpage_go(1610, 'custom-combined', 17)
    h = struct.unpack_from('<IIII', data, 0)
    obj_words = struct.unpack_from('<' + 'I' * 35, data, 16)
    print(f'  Size: {len(data)} bytes')
    print(f'  Header: tag=0x{h[0]:08X} len={h[1]} ver={h[2]} code_size={h[3]}')
    print(f'  tpage id={obj_words[3]} length={obj_words[4]}')
    assert h[2] == 4, "Expected v4"
    assert obj_words[3] == 1610
    assert obj_words[4] == 17
    print('  PASS')

    print()
    print('=== dir-tpages.go writer test ===')
    id_to_len = {2: 64, 13: 160, 41: 93, 52: 85, 385: 82, 659: 93, 1610: 17}
    data = build_dir_tpages_go(id_to_len)
    h = struct.unpack_from('<IIII', data, 0)
    print(f'  Size: {len(data)} bytes')
    print(f'  Header: tag=0x{h[0]:08X} ver={h[2]} code_size={h[3]}')
    print(f'  Covers IDs 0-{max(id_to_len)} = {max(id_to_len)+1} entries')
    assert h[2] == 4, "Expected v4"
    print('  PASS')

    print()
    print('All tests passed.')
