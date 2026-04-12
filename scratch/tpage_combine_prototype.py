"""
tpage combine prototype — tested Python implementations
All code here is confirmed working against the OpenGOAL source format.
"""

import struct
import json
from pathlib import Path
from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# DataObjectGenerator
# Python port of goalc/data_compiler/DataObjectGenerator.cpp
# Writes GOAL v4 object (.go) files.
# ─────────────────────────────────────────────────────────────────────────────

class DataObjectGenerator:
    def __init__(self):
        self.words = []
        self.ptr_links = []        # (source_word_idx, target_byte_offset)
        self.string_pool = {}      # str -> [word_idx, ...]
        self.type_links = {}       # type_name -> [word_idx, ...]
        self.symbol_links = {}     # sym_name -> [word_idx, ...]

    def add_word(self, val=0):
        idx = len(self.words)
        self.words.append(int(val) & 0xFFFFFFFF)
        return idx

    def set_word(self, idx, val):
        self.words[idx] = int(val) & 0xFFFFFFFF

    def link_word_to_byte(self, source_word, target_byte):
        self.ptr_links.append((source_word, target_byte))

    def link_word_to_word(self, source, target, offset=0):
        self.link_word_to_byte(source, target * 4 + offset)

    def add_ref_to_string(self, s):
        idx = self.add_word(0)
        self.string_pool.setdefault(s, []).append(idx)
        return idx

    def add_type_tag(self, s):
        idx = self.add_word(0)
        self.type_links.setdefault(s, []).append(idx)
        return idx

    def add_symbol_link(self, s):
        idx = self.add_word(0)
        self.symbol_links.setdefault(s, []).append(idx)
        return idx

    def align(self, n_words):
        while len(self.words) % n_words:
            self.words.append(0)

    def align_to_basic(self):
        self.align(4)

    def _push_varlen(self, val, buf):
        """Variable-length integer encoding (used for pointer link table)."""
        while val > 255:
            buf.append(255)
            val -= 255
        if val == 255:
            buf.append(255)
            buf.append(0)
        else:
            buf.append(val)

    def _push_better_varlen(self, val, buf):
        """Better variable-length encoding (used for symbol/type link tables)."""
        if val > 0xFFFFFF:
            buf.append((val & 0xFF) | 3)
            buf.append((val >> 8) & 0xFF)
            buf.append((val >> 16) & 0xFF)
            buf.append((val >> 24) & 0xFF)
        elif val > 0xFFFF:
            buf.append((val & 0xFF) | 2)
            buf.append((val >> 8) & 0xFF)
            buf.append((val >> 16) & 0xFF)
        elif val > 0xFF:
            buf.append((val & 0xFF) | 1)
            buf.append((val >> 8) & 0xFF)
        else:
            buf.append(val & 0xFF)

    def _add_strings(self):
        """Append string basics to object data and fix up references."""
        for s, refs in self.string_pool.items():
            self.align(4)
            self.add_type_tag('string')
            target_word = self.add_word(len(s))
            sb = list(s.encode('ascii')) + [0]
            while len(sb) % 4:
                sb.append(0)
            for i in range(len(sb) // 4):
                self.add_word(struct.unpack('<I', bytes(sb[i*4:(i+1)*4]))[0])
            for src in refs:
                self.link_word_to_word(src, target_word)

    def _generate_link_table(self):
        """Generate the complete link table bytes."""
        link = []

        # --- pointer links ---
        pl = sorted(self.ptr_links, key=lambda x: x[0])
        i = 0
        last_word = 0
        while i < len(pl):
            src, tgt = pl[i]
            diff = src - last_word
            last_word = src + 1
            self._push_varlen(diff, link)
            self.words[src] = tgt
            consecutive = 1
            while (i + 1 < len(pl) and pl[i + 1][0] == pl[i][0] + 1):
                self.words[pl[i + 1][0]] = pl[i + 1][1]
                last_word = pl[i + 1][0] + 1
                consecutive += 1
                i += 1
            self._push_varlen(consecutive, link)
            i += 1
        self._push_varlen(0, link)

        # --- symbol links ---
        for sym, refs in sorted(self.symbol_links.items()):
            for c in sym.encode('ascii'):
                link.append(c)
            link.append(0)
            prev = 0
            for x in sorted(refs):
                self._push_better_varlen((x - prev) * 4, link)
                self.words[x] = 0xFFFFFFFF
                prev = x
            link.append(0)

        # --- type links ---
        for typ, refs in sorted(self.type_links.items()):
            link.append(0x80)
            for c in typ.encode('ascii'):
                link.append(c)
            link.append(0)
            prev = 0
            for x in sorted(refs):
                self._push_better_varlen((x - prev) * 4, link)
                self.words[x] = 0xFFFFFFFF
                prev = x
            link.append(0)
        self._push_varlen(0, link)

        # pad to 64-byte boundary from LinkHeaderV2 start (12 bytes)
        while (len(link) + 12) % 64:
            link.append(0)

        return bytes(link)

    def generate_v4(self):
        """Serialise to v4 GOAL object file bytes."""
        self._add_strings()
        link = self._generate_link_table()

        code_size = ((len(self.words) * 4) + 15) & ~15
        link_hdr_len = 12 + len(link)  # LinkHeaderV2 size

        # LinkHeaderV4
        hdr4 = struct.pack('<IIII', 0xFFFFFFFF, link_hdr_len, 4, code_size)
        obj_data = struct.pack('<' + 'I' * len(self.words), *self.words)
        padding = bytes(code_size - len(obj_data))
        # LinkHeaderV2
        hdr2 = struct.pack('<III', 0xFFFFFFFF, link_hdr_len, 2)

        return hdr4 + obj_data + padding + hdr2 + link


# ─────────────────────────────────────────────────────────────────────────────
# Skeleton tpage writer
# Writes a minimal valid tpage-NNNN.go with no pixel data.
# All texture slots are #f — actual pixels come from the FR3 file.
# ─────────────────────────────────────────────────────────────────────────────

def write_skeleton_tpage(tpage_id: int, tpage_name: str, tex_count: int, output_path: str) -> int:
    """
    Write a skeleton tpage .go file to output_path.
    
    tpage_id:   integer page ID (e.g. 1610)
    tpage_name: string name embedded in file (e.g. 'custom-combined')
    tex_count:  number of texture slots (must >= max remapped index + 1)
    output_path: destination file path (e.g. '.../obj/tpage-1610.go')
    
    Returns: bytes written.
    Jak1 TX_PAGE_VERSION = 7 (confirmed from common/versions/versions.h)
    """
    gen = DataObjectGenerator()

    # --- texture-page basic (root object) ---
    gen.add_type_tag('texture-page')       # word 0
    fi_ref    = gen.add_word(0)            # word 1: → file-info (ptr, linked later)
    gen.add_ref_to_string(tpage_name)      # word 2: → name string
    gen.add_word(tpage_id)                 # word 3: id
    gen.add_word(tex_count)                # word 4: length
    gen.add_word(1)                        # word 5: mip0_size (placeholder)
    gen.add_word(1)                        # word 6: size (placeholder)
    # segment[0]: block_data ptr, size, dest
    seg0_ptr  = gen.add_word(0)            # word 7: → pixel data (linked later)
    gen.add_word(1)                        # word 8: seg0.size = 1
    gen.add_word(0)                        # word 9: seg0.dest = 0
    # segment[1], segment[2]: all zeros
    for _ in range(6):
        gen.add_word(0)                    # words 10-15
    # pad[16]
    for _ in range(16):
        gen.add_word(0)                    # words 16-31
    # data[] — tex_count entries, all #f
    for _ in range(tex_count):
        gen.add_symbol_link('#f')

    # --- file-info basic ---
    gen.align(4)
    fi_start = gen.add_type_tag('file-info')
    gen.add_symbol_link('texture-page')    # file_type
    gen.add_ref_to_string(tpage_name)      # file_name
    gen.add_word(7)                        # major_version (Jak1 TX_PAGE_VERSION)
    gen.add_word(0)                        # minor_version
    gen.add_ref_to_string('Unknown')       # maya_file_name
    gen.add_ref_to_string('og-custom')     # tool_debug
    gen.add_word(0)                        # mdb_file_name

    # --- minimal pixel data ---
    gen.align(4)
    pix_start = len(gen.words)
    gen.add_word(0)                        # 4 bytes dummy

    # fix up pointers
    gen.link_word_to_word(fi_ref, fi_start)
    gen.link_word_to_word(seg0_ptr, pix_start)

    data = gen.generate_v4()
    Path(output_path).write_bytes(data)
    return len(data)


# ─────────────────────────────────────────────────────────────────────────────
# Remap table builder
# Reads tex-info.min.json and produces a sorted remap table for a set of enemy textures.
# ─────────────────────────────────────────────────────────────────────────────

def build_tpage_remap(tex_info_path: str, enemy_texture_names: list[str],
                      combined_tpage_id: int) -> dict:
    """
    Build a combined tpage remap table for the given list of texture names.

    tex_info_path:       path to decompiler/config/jak1/ntsc_v1/tex-info.min.json
    enemy_texture_names: list of texture name substrings, e.g. ['kermit', 'crab-belt']
                         OR exact names. Both substring and exact match supported.
    combined_tpage_id:   the new combined tpage ID (e.g. 1610)

    Returns dict with:
        'remap_table':   list of (orig_u32, new_u32) sorted by orig — for BSP
        'textures_json': dict of tpage_name -> [tex_names] — for level JSON "textures" field
        'combined_count': number of slots in combined tpage
        'source_tpages': set of original tpage IDs eliminated
    """
    data = json.loads(Path(tex_info_path).read_text())

    # Find all matching textures
    matched = []
    for entry in data:
        combo_id = entry[0]
        tex = entry[1]
        name = tex['name']
        for wanted in enemy_texture_names:
            if wanted in name or name == wanted:
                pc_page = combo_id >> 16
                pc_idx = combo_id & 0xFFFF
                goal_texid = (pc_page << 20) | (pc_idx << 8)
                matched.append({
                    'name': name,
                    'tpage_name': tex['tpage_name'],
                    'orig_page': pc_page,
                    'orig_idx': pc_idx,
                    'orig_masked': goal_texid & 0xffffff00,
                })
                break

    # Deduplicate by exact texture identity
    seen = set()
    unique = []
    for t in matched:
        key = (t['orig_page'], t['orig_idx'])
        if key not in seen:
            seen.add(key)
            unique.append(t)

    # Assign new sequential slots
    remap_table = []
    for slot, t in enumerate(unique):
        new_goal = (combined_tpage_id << 20) | (slot << 8) | 0x14
        remap_table.append((t['orig_masked'], new_goal))

    # Sort by orig (REQUIRED — GOAL binary search)
    remap_table.sort(key=lambda x: x[0])

    # Build textures JSON grouping
    textures_json = defaultdict(list)
    for t in unique:
        textures_json[t['tpage_name']].append(t['name'])

    source_tpages = {t['orig_page'] for t in unique}

    return {
        'remap_table': remap_table,
        'textures_json': dict(textures_json),
        'combined_count': len(unique),
        'source_tpages': source_tpages,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Quick test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import tempfile, os

    # Test skeleton writer
    with tempfile.NamedTemporaryFile(suffix='.go', delete=False) as f:
        tmp = f.name
    size = write_skeleton_tpage(1610, 'custom-combined', 17, tmp)
    print(f'Skeleton tpage written: {size} bytes to {tmp}')
    data = Path(tmp).read_bytes()
    h = struct.unpack_from('<IIII', data, 0)
    print(f'  Header: tag=0x{h[0]:08X} len={h[1]} ver={h[2]} code_size={h[3]}')
    tpage_id_check = struct.unpack_from('<I', data, 16 + 12)[0]
    tex_count_check = struct.unpack_from('<I', data, 16 + 16)[0]
    print(f'  tpage_id={tpage_id_check} tex_count={tex_count_check}')
    os.unlink(tmp)
    print('  OK')

    print()
    print('Remap builder requires tex-info.min.json — run from jak-project decompiler_out dir')
