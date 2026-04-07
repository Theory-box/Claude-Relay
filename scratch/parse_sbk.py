"""
Jak 1 SBK parser — extracts sound names from each .SBK file.
Run this from anywhere. Output: sbk_sounds.json in the same folder.

Usage: py parse_sbk.py
"""

import struct
import json
from pathlib import Path

BLOCK_HAS_NAMES = 0x100

def fourcc(s):
    # little-endian fourcc
    b = s.encode('ascii')
    return struct.unpack('<I', b)[0]

SBLK = fourcc('SBlk')

def parse_sbk(filepath):
    data = Path(filepath).read_bytes()
    if len(data) < 8:
        return None, []

    # FileAttributes header
    fa_type    = struct.unpack_from('<I', data, 0)[0]
    num_chunks = struct.unpack_from('<I', data, 4)[0]

    if num_chunks < 2 or num_chunks > 8:
        return None, []

    chunks = []
    for i in range(num_chunks):
        offset = struct.unpack_from('<I', data, 8 + i*8)[0]
        size   = struct.unpack_from('<I', data, 8 + i*8 + 4)[0]
        chunks.append((offset, size))

    bank_offset, bank_size = chunks[0]
    # size=0 means "rest of file" in some versions
    if bank_size == 0:
        bank_size = len(data) - bank_offset
    bd = data[bank_offset : bank_offset + bank_size]

    if len(bd) < 4:
        return None, []

    data_id = struct.unpack_from('<I', bd, 0)[0]
    if data_id != SBLK:
        return None, []  # music bank (SBv2) — skip

    version = struct.unpack_from('<I', bd, 4)[0]
    flags   = struct.unpack_from('<I', bd, 8)[0]

    # Skip ahead to BlockNames offset
    # Header layout (bytes):
    #  0: DataID u32
    #  4: Version u32
    #  8: Flags u32
    # 12: BankID u32
    # 16: BankNum s8
    # 17: pad s8
    # 18: pad s16
    # 20: pad s16
    # 22: NumSounds s16
    # 24: NumGrains s16
    # 26: NumVAGs s16
    # 28: FirstSound u32
    # 32: FirstGrain u32
    # 36: VagsInSR u32
    # 40: VagDataSize u32
    # 44: SRAMAllocSize u32
    # 48: NextBlock u32
    # 52: GrainData u32  (only if version >= 2)
    # 52 or 56: BlockNames u32

    if version >= 2:
        block_names_pos = 56
    else:
        block_names_pos = 52

    if block_names_pos + 4 > len(bd):
        return None, []

    block_names = struct.unpack_from('<I', bd, block_names_pos)[0]

    bank_name   = Path(filepath).stem.lower()
    sound_names = []

    if (flags & BLOCK_HAS_NAMES) and 0 < block_names < len(bd):
        # SFXBlockNames layout:
        #  +0x00  u32 BlockName[2]          (8 bytes — bank name string)
        #  +0x08  u32 SFXNameTableOffset
        #  +0x0c  u32 VAGNameTableOffset
        #  +0x10  u32 VAGImportsTableOffset
        #  +0x14  u32 VAGExportsTableOffset
        #  +0x18  s16 SFXHashOffsets[32]    (64 bytes)
        #  +0x58  s16 VAGHashOffsets[32]    (64 bytes)

        p = block_names
        if p + 0x18 + 64 > len(bd):
            return bank_name, []

        raw_name = bd[p : p+8].rstrip(b'\x00')
        try:
            bank_name = raw_name.decode('ascii').lower()
        except Exception:
            pass

        sfx_table_off    = struct.unpack_from('<I',  bd, p + 0x08)[0]
        sfx_hash_offsets = struct.unpack_from('<32h', bd, p + 0x18)
        name_table_base  = block_names + sfx_table_off

        # SFXName: 16-byte name + s16 Index + s16 reserved = 0x14 bytes per entry
        seen = set()
        for hash_offset in sfx_hash_offsets:
            entry_pos = name_table_base + hash_offset * 0x14
            while entry_pos + 0x14 <= len(bd):
                raw = bd[entry_pos : entry_pos + 16]
                if raw[:4] == b'\x00\x00\x00\x00':
                    break
                try:
                    name = raw.rstrip(b'\x00').decode('ascii').lower().replace('_', '-')
                except Exception:
                    break
                if not name:
                    break
                if name not in seen:
                    seen.add(name)
                    sound_names.append(name)
                entry_pos += 0x14

    return bank_name, sorted(sound_names)


def main():
    sbk_dir = Path(r"C:\Users\John\Documents\JakAndDaxter\active\jak1\data\iso_data\jak1\SBK")
    if not sbk_dir.exists():
        print(f"SBK folder not found:\n  {sbk_dir}")
        input("Press Enter to exit.")
        return

    results = {}
    for sbk_file in sorted(sbk_dir.glob("*.SBK")):
        bank_name, names = parse_sbk(sbk_file)
        if names:
            print(f"  {sbk_file.name:22s} → {len(names):3d} sounds")
            results[bank_name] = names
        else:
            print(f"  {sbk_file.name:22s} → skipped (music/empty/unrecognised)")

    out = Path(__file__).parent / "sbk_sounds.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nDone. {len(results)} banks, {sum(len(v) for v in results.values())} total sounds.")
    print(f"Written to: {out}")
    input("\nPress Enter to exit.")

if __name__ == "__main__":
    main()
