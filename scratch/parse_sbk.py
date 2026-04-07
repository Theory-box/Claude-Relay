"""
Jak 1 SBK parser — extracts sound names from each .SBK file.
Run this from anywhere. Output: sbk_sounds.json in the same folder.

Usage: python parse_sbk.py
"""

import struct
import json
from pathlib import Path

BLOCK_HAS_NAMES = 0x100

def fourcc(s):
    return struct.unpack('<I', s.encode('ascii'))[0]

SBLK = fourcc('SBlk')

def parse_file_attributes(data):
    fa_type, num_chunks = struct.unpack_from('<II', data, 0)
    chunks = []
    for i in range(num_chunks):
        offset, size = struct.unpack_from('<II', data, 8 + i * 8)
        chunks.append((offset, size))
    return num_chunks, chunks

def parse_sbk(filepath):
    data = Path(filepath).read_bytes()
    num_chunks, chunks = parse_file_attributes(data)
    if num_chunks < 2:
        return None, []

    bank_offset, bank_size = chunks[0]
    bd = data[bank_offset : bank_offset + bank_size]

    pos = 0
    data_id = struct.unpack_from('<I', bd, pos)[0]; pos += 4
    if data_id != SBLK:
        return None, []  # music bank (SBv2) — skip

    version = struct.unpack_from('<I', bd, pos)[0]; pos += 4
    flags   = struct.unpack_from('<I', bd, pos)[0]; pos += 4
    pos += 4  # BankID
    pos += 1  # BankNum
    pos += 1  # padding
    pos += 2  # padding
    pos += 2  # padding
    pos += 2  # NumSounds
    pos += 2  # NumGrains
    pos += 2  # NumVAGs
    pos += 4  # FirstSound
    pos += 4  # FirstGrain
    pos += 4  # VagsInSR
    pos += 4  # VagDataSize
    pos += 4  # SRAMAllocSize
    pos += 4  # NextBlock
    if version >= 2:
        pos += 4  # GrainData
    block_names = struct.unpack_from('<I', bd, pos)[0]; pos += 4

    bank_name  = Path(filepath).stem.lower()
    sound_names = []

    if (flags & BLOCK_HAS_NAMES) and 0 < block_names < len(bd):
        # SFXBlockNames layout:
        #   u32 BlockName[2]           +0x00  (8 bytes — bank name)
        #   u32 SFXNameTableOffset     +0x08
        #   u32 VAGNameTableOffset     +0x0c
        #   u32 VAGImportsTableOffset  +0x10
        #   u32 VAGExportsTableOffset  +0x14
        #   s16 SFXHashOffsets[32]     +0x18  (64 bytes)
        #   s16 VAGHashOffsets[32]     +0x58  (64 bytes)

        raw_name = bd[block_names : block_names + 8].rstrip(b'\x00')
        bank_name = raw_name.decode('ascii', errors='replace').lower()

        sfx_table_off   = struct.unpack_from('<I', bd, block_names + 0x08)[0]
        sfx_hash_offsets = struct.unpack_from('<32h', bd, block_names + 0x18)
        name_table_base  = block_names + sfx_table_off

        # SFXName: u32 Name[4] (16 bytes) + s16 Index + s16 reserved = 0x14 bytes
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
                if name and name not in seen:
                    seen.add(name)
                    sound_names.append(name)
                entry_pos += 0x14

    return bank_name, sorted(sound_names)


def main():
    sbk_dir = Path(r"C:\Users\John\Documents\JakAndDaxter\active\jak1\data\iso_data\jak1\SBK")
    if not sbk_dir.exists():
        print(f"SBK folder not found at:\n  {sbk_dir}")
        print("Edit the sbk_dir path at the bottom of this script.")
        input("Press Enter to exit.")
        return

    results = {}
    for sbk_file in sorted(sbk_dir.glob("*.SBK")):
        bank_name, names = parse_sbk(sbk_file)
        if names:
            print(f"  {sbk_file.name:20s} → {len(names):3d} sounds  (bank: {bank_name})")
            results[bank_name] = names
        else:
            print(f"  {sbk_file.name:20s} → skipped (music bank or no names)")

    out = Path(__file__).parent / "sbk_sounds.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nDone. Written to:\n  {out}")
    print(f"Total: {len(results)} banks, {sum(len(v) for v in results.values())} sounds")
    input("\nPress Enter to exit.")

if __name__ == "__main__":
    main()
