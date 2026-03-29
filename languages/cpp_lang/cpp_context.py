def extract_cpp_context(file_path, line_number, window=20):

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = max(0, line_number - window)
    end = min(len(lines), line_number + window)

    return "".join(lines[start:end])