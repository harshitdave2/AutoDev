def extract_context(file_path, line, window=20):

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = max(0, line - window)
    end = min(len(lines), line + window)

    return "".join(lines[start:end])
