import unicodedata

files = [
    'agent/retry_manager.py',
    'models/model_orchestrator.py', 
    'models/ollama_model.py',
    'agent/agent.py',
    'core/sanitizer.py',
    'core/syntax_repair.py',
    'autodev.py',
    'cli/main.py',
]

with open('all_unicode.txt', 'w', encoding='utf-8') as out:
    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            bad = {}
            for i, ch in enumerate(content):
                cp = ord(ch)
                if cp > 127:
                    if cp not in bad:
                        bad[cp] = []
                    bad[cp].append(i)
            if bad:
                out.write(f'\n{fpath}:\n')
                for cp in sorted(bad.keys()):
                    name = unicodedata.name(chr(cp), '?')
                    out.write(f'  U+{cp:04X} ({name}): {len(bad[cp])} occurrence(s)\n')
        except Exception as e:
            out.write(f'{fpath}: ERROR {e}\n')
