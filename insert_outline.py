"""Helper script to insert _extract_cpp_outline_methods into function_patch_merger.py"""

target = 'd:/AUTODEV/autodev/core/function_patch_merger.py'
content = open(target, 'r', encoding='utf-8').read()

if '_extract_cpp_outline_methods' in content:
    print('Method already exists — nothing to do.')
else:
    marker = '    @staticmethod\n    def _cpp_has_function'
    insert_at = content.find(marker)
    if insert_at == -1:
        print('ERROR: marker not found')
    else:
        new_method = (
            '    @staticmethod\n'
            '    def _extract_cpp_outline_methods(source):\n'
            '        """\n'
            '        Extract out-of-line C++ class method definitions using ClassName::methodName\n'
            '        notation (e.g. int Student::getId() { return id_; }).\n'
            '        Returns dict: "ClassName::methodName" -> inline method source.\n'
            '        """\n'
            '        import re as _re\n'
            '        from typing import Dict\n'
            '        methods: Dict[str, str] = {}\n'
            '        sig_pattern = _re.compile(\n'
            r"            r'(?:[\w*&<>\s]*)?\b(\w+)::(\w+)\s*\([^)]*\)\s*(?:const|noexcept|override)?\s*\{',"
            '\n'
            '            _re.MULTILINE,\n'
            '        )\n'
            '        for m in sig_pattern.finditer(source):\n'
            '            class_name = m.group(1)\n'
            '            method_name = m.group(2)\n'
            "            if method_name in ('if', 'for', 'while', 'switch', 'catch'):\n"
            '                continue\n'
            '            qualified = f"{class_name}::{method_name}"\n'
            '            try:\n'
            "                brace_start = source.index('{', m.start())\n"
            '            except ValueError:\n'
            '                continue\n'
            '            depth = 0\n'
            '            end = brace_start\n'
            '            for i, ch in enumerate(source[brace_start:], brace_start):\n'
            "                if ch == '{':\n"
            '                    depth += 1\n'
            "                elif ch == '}':\n"
            '                    depth -= 1\n'
            '                    if depth == 0:\n'
            '                        end = i + 1\n'
            '                        break\n'
            '            raw_src = source[m.start():end].strip()\n'
            '            # Strip the ClassName:: qualifier from the method signature\n'
            '            inline_src = _re.sub(\n'
            r"                r'\b' + _re.escape(class_name) + r'::(' + _re.escape(method_name) + r')',"
            '\n'
            r"                r'\1',"
            '\n'
            '                raw_src,\n'
            '                count=1,\n'
            '            )\n'
            '            methods[qualified] = inline_src\n'
            '        return methods\n'
            '\n'
        )
        content = content[:insert_at] + new_method + content[insert_at:]
        open(target, 'w', encoding='utf-8').write(content)
        print('INSERTED OK')
