# AutoDev — AI Debugging Agent

AutoDev is a command-line AI debugging system that can automatically detect and repair bugs in **Python, C++, and Java** programs.

It analyzes runtime failures, logical anomalies, and compiler errors, then uses AI models to generate candidate fixes and test them automatically.

---

## Features

* Automatic bug detection
* AI-generated code repair
* Supports **Python, C++, Java**
* Local LLM support (Ollama)
* Cloud model fallback
* Patch validation system
* Bug memory for repeated fixes
* CLI based workflow

---

## Architecture

AutoDev pipeline:

CLI
→ Language Router
→ Runner
→ Analyzer
→ AutoDev Agent
→ LLM Repair
→ Patch Engine
→ Retry Manager
→ Execution Validation

---

## Quick Start

**Clone the repository**

```bash
git clone https://github.com/harshitdave2/AutoDev
cd AutoDev
```

**Install dependencies**

```bash
pip install -r requirements.txt
```

**Install a local coding model**

```bash
ollama pull deepseek-coder:6.7b
```

**Run AutoDev**

```bash
python autodev.py run examples/broken_python.py
python autodev.py run examples/broken_cpp.cpp
python autodev.py run examples/broken_java.java
```

---

## CLI Options

```
python autodev.py run <file> [options]
```

Options:

| Option          | Description                    |
| --------------- | ------------------------------ |
| `--max-retries` | number of repair attempts      |
| `--dry-run`     | preview patch without applying |
| `--help`        | show command help              |

---

## Supported Languages

| Language | Status    |
| -------- | --------- |
| Python   | Supported |
| C++      | Supported |
| Java     | Supported |

---

## Example Output

```
=== Initial Execution Check ===
⚠ Suspicious output detected

Proceeding with repair attempts...

✔ Script fixed successfully!
```

---

## Project Goal

AutoDev aims to provide a lightweight autonomous debugging tool that can automatically repair common programming errors using AI models.

---

## License

MIT License
