import unicodedata, os

files_to_check = [
    'agent/agent.py',
    'models/ollama_model.py',
    'core/runner.py',
    'core/analyzer.py',
]

for fpath in files_to_check:
    if not os.path.exists(fpath):
        continue
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    bad = set(ord(ch) for ch in content if ord(ch) > 127)
    if bad:
        print(f'{fpath}: {[hex(cp) for cp in sorted(bad)]}')
