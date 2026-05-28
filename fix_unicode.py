import sys

with open('agent/retry_manager.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacements = {
    '\u2718': 'X',         # ✘ heavy ballot X
    '\u2714': 'OK',        # ✔ heavy check mark
    '\u26a0': '!',         # ⚠ warning sign
    '\u2716': 'X',         # ✖ heavy multiplication X
    '\u2192': '->',        # → rightwards arrow
    '\u2014': '--',        # — em dash
    '\ufe0f': '',          # variation selector-16 (invisible modifier)
    '\u20e3': '',          # combining enclosing keycap
    '\U0001f9e0': '[AI]',  # 🧠 brain
    '\U0001f527': '[W]',   # 🔧 wrench
    '\U0001f3af': '[T]',   # 🎯 dart/target
    '\U0001f680': '[^]',   # 🚀 rocket
    '\u26a1': '^',         # ⚡ lightning
    '\U0001f4a5': '!',     # 💥 collision
    '\U0001f6a7': '!',     # 🚧 construction
}

original = content
for old, new in replacements.items():
    content = content.replace(old, new)

# Also replace numbered emoji like 1️⃣ 2️⃣ etc  
import re
content = re.sub(r'([0-9])\ufe0f\u20e3', r'\1.', content)

changed = content != original
if changed:
    with open('agent/retry_manager.py', 'w', encoding='utf-8') as f:
        f.write(content)

# Verify
import unicodedata
remaining = set(ord(ch) for ch in content if ord(ch) > 127)
with open('unicode_chars2.txt', 'w', encoding='utf-8') as out:
    out.write(f'Changed: {changed}\n')
    out.write(f'Remaining non-ASCII codepoints: {len(remaining)}\n')
    for cp in sorted(remaining):
        ch = chr(cp)
        out.write(f'  U+{cp:04X}  {unicodedata.name(ch, "?")}\n')
