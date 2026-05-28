    @staticmethod
    def _extract_cpp_outline_methods(source):
        """
        Extract out-of-line C++ class method definitions using ClassName::methodName notation.

        These are definitions like:
            int Student::getId() { return id_; }
            void Matrix::multiply(int n) { ... }

        Returns dict: "ClassName::methodName" -> inline method source (ClassName:: prefix stripped).
        """
        import re as _re
        methods = {}
        sig_pattern = _re.compile(
            r'(?:[\w*&<>\s]*)?\b(\w+)::(\w+)\s*\([^)]*\)\s*(?:const|noexcept|override)?\s*\{',
            _re.MULTILINE,
        )
        for m in sig_pattern.finditer(source):
            class_name = m.group(1)
            method_name = m.group(2)
            if method_name in ('if', 'for', 'while', 'switch', 'catch'):
                continue
            qualified = class_name + '::' + method_name
            try:
                brace_start = source.index('{', m.start())
            except ValueError:
                continue
            depth = 0
            end = brace_start
            for i, ch in enumerate(source[brace_start:], brace_start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            raw_src = source[m.start():end].strip()
            # Strip the ClassName:: qualifier for inline injection
            inline_src = _re.sub(
                r'\b' + _re.escape(class_name) + r'::(' + _re.escape(method_name) + r')',
                r'\1',
                raw_src,
                count=1,
            )
            methods[qualified] = inline_src
        return methods

