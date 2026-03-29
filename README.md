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

## Installation

Clone the repository:

```
git clone https://github.com/yourname/autodev.git
cd autodev
```

Install dependencies:

```
pip install -r requirements.txt
```

Install Ollama (for local models):

```
https://ollama.ai
```

Pull a coding model:

```
ollama pull deepseek-coder:6.7b
```

---

## Usage

Run AutoDev on a file:

```
python autodev.py run myfile.py
```

Examples:

```
python autodev.py run buggy_matrix.cpp
python autodev.py run PseudoCode.java
python autodev.py run broken_script.py
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
