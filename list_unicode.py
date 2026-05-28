import sys
import unicodedata

with open('agent/retry_manager.py', 'r', encoding='utf-8') as f:
    content = f.read()

bad = [(i+1, ch, unicodedata.name(ch, '?')) for i, ch in enumerate(content) if ord(ch) > 127]

# Write results to file to avoid console encoding issues
with open('unicode_chars.txt', 'w', encoding='utf-8') as out:
    out.write(f'Total non-ASCII chars: {len(bad)}\n')
    seen = set()
    for pos, ch, name in bad:
        key = ord(ch)
        if key not in seen:
            seen.add(key)
            out.write(f'  U+{key:04X}  {repr(ch)}  {name}\n')
