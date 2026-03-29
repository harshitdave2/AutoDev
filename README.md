⚠️ AutoDev is an experimental AI debugging system. Use with caution on production code.
# AutoDev — Autonomous AI Debugging Agent

AutoDev is an **AI-powered debugging system** that automatically detects and repairs bugs in **Python, C++, and Java** programs.

It executes the target program, analyzes failures, and uses **LLMs to generate and test candidate fixes** until the program runs successfully.

---

## Features

* Automatic bug detection
* AI-generated code repair
* Supports **Python, C++, Java**
* Local LLM support via **Ollama**
* Cloud model fallback
* Patch validation system
* Bug memory for repeated fixes
* CLI-based debugging workflow
* Multi-attempt repair loop

---

## Architecture

AutoDev debugging pipeline:

```
CLI
 → Language Router
 → Runner
 → Analyzer
 → AutoDev Agent
 → LLM Repair
 → Patch Engine
 → Retry Manager
 → Execution Validation
```

This architecture enables AutoDev to automatically analyze crashes, generate fixes, and test them safely.

---

## Installation

### 1. Clone the repository

```
git clone https://github.com/harshitdave2/AutoDev
cd AutoDev
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Install Ollama (for local AI models)

Download from:

```
https://ollama.ai
```

### 4. Install a coding model

Example:

```
ollama pull deepseek-coder:6.7b
```

You may also use:

```
ollama pull qwen2.5-coder:7b
```

---

## Quick Start

Run AutoDev on a program:

```
python autodev.py run myfile.py
```

Examples:

```
python autodev.py run examples/broken_python.py
python autodev.py run examples/broken_cpp.cpp
python autodev.py run examples/broken_java.java
```

---

## CLI Usage

```
python autodev.py run <file> [options]
```

Options:

| Option          | Description                 |
| --------------- | --------------------------- |
| `--max-retries` | Maximum repair attempts     |
| `--dry-run`     | Show patch without applying |
| `--help`        | Display command help        |

Example:

```
python autodev.py run buggy_matrix.cpp --max-retries 5
```

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

## Project Structure

```
AutoDev/
│
├── agent/
├── core/
├── languages/
├── models/
│
├── examples/
│   ├── broken_python.py
│   ├── broken_cpp.cpp
│   └── broken_java.java
│
├── autodev.py
├── README.md
├── requirements.txt
└── LICENSE
```

---

## Model Configuration

AutoDev works with **local models via Ollama**.

Recommended models:

| Model               | Use                            |
| ------------------- | ------------------------------ |
| deepseek-coder:6.7b | Fast and reliable code repair  |
| qwen2.5-coder:7b    | Strong reasoning for debugging |

---

## Roadmap

Planned improvements:

* Better logical bug detection
* AST-based bug localization
* Multi-agent repair system
* Test-case generation
* IDE integration
* Web dashboard

---

## Contributing

Contributions are welcome!

You can help by:

* Adding new language support
* Improving repair accuracy
* Improving validation heuristics
* Fixing bugs

Open an issue or submit a pull request.

---

## License

MIT License
