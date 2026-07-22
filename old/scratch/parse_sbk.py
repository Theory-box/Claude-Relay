"""
Jak 1 SBK parser — extracts sound names from each .SBK file.
Run this from anywhere. Output: sbk_sounds.json in the same folder.

Usage: py parse_sbk.py
"""

import struct
import json
from pathlib import Path

def parse_sbk(filepath):
    data = Path(filepath).read_bytes()
    if len(data) < 0x18:
        return None, []

    # SBK prefix layout (before the binary FA/SBlk section):
    #   0x00: bank name (16 bytes, null-padded)
    #   0x10: u32 unknown (0)
    #   0x14: u32 num_sounds
    #   0x18: entries — each is 16-byte name + 4-byte params = 20 bytes each

    bank_name = data[:16].rstrip(b'\x00').decode('ascii', errors='replace').lower()
    num_sounds = struct.unpack_from('<I', data, 0x14)[0]

    # Sanity check — reject obviously wrong values
    if num_sounds == 0 or num_sounds > 2000:
        return bank_name, []

    names = []
    pos = 0x18
    for i in range(num_sounds):
        if pos + 20 > len(data):
            break
        raw  = data[pos:pos+16]
        name = raw.rstrip(b'\x00').decode('ascii', errors='replace').lower().replace('_', '-')
        if name and not name.startswith('\x00'):
            names.append(name)
        pos += 20

    return bank_name, sorted(names)


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
            print(f"  {sbk_file.name:22s} → skipped (empty or unrecognised)")

    out = Path(__file__).parent / "sbk_sounds.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nDone. {len(results)} banks, {sum(len(v) for v in results.values())} total sounds.")
    print(f"Written to: {out}")
    input("\nPress Enter to exit.")

if __name__ == "__main__":
    main()
