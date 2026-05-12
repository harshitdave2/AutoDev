⚠️ AutoDev is an experimental AI debugging system. Use with caution on production code.
# AutoDev — Autonomous Developer Agent

> **An AI-powered agent that detects, analyzes, patches, and validates bugs in your code — automatically.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![LLM: Ollama | Groq | Gemini](https://img.shields.io/badge/LLM-Ollama%20%7C%20Groq%20%7C%20Gemini-blueviolet)]()
[![Status: Active Development](https://img.shields.io/badge/Status-Active%20Development-green)]()

---

## What is AutoDev?

AutoDev is an autonomous debugging and code-repair agent built for developers who want more than just a linter or a static analyzer. It acts as a self-healing assistant — one that understands broken programs, generates intelligent repair candidates using LLMs, applies patches, tests the result, and retries when needed.

Rather than just flagging errors, AutoDev **fixes them**.

It is designed to work with local models via [Ollama](https://ollama.com/) for full offline capability, and falls back gracefully to cloud providers like [Groq](https://groq.com/) and [Gemini](https://deepmind.google/technologies/gemini/) when needed. AutoDev is modular, CLI-driven, and built to scale alongside your workflow.

---

## Why AutoDev?

Modern debugging tools are powerful — but they still leave the hardest part to you. AutoDev closes that gap by treating bug repair as an end-to-end autonomous task:

- **You run a broken file. AutoDev figures out what's wrong and fixes it.**
- No manual root cause analysis. No hand-written patches. No wasted cycles.

It is designed for developers who want to move faster, for teams that need automated repair pipelines, and for researchers exploring autonomous coding agents.

---

## Key Features

| Feature | Description |
|---|---|
| **Autonomous Bug Detection** | Captures runtime errors, compiler failures, and logical faults automatically |
| **AI-Generated Code Repair** | Generates targeted patch candidates using local or cloud LLMs |
| **Local & Cloud Model Support** | Works with Ollama (local), Groq, and Gemini — with automatic fallback |
| **Patch Validation** | Applies fixes and re-executes to verify correctness before accepting |
| **Retry Logic** | Intelligently retries with alternate strategies when an initial patch fails |
| **Bug Memory / Context Engine** | Remembers recurring patterns and past fixes to improve over time |
| **CLI Workflow** | Clean, simple command-line interface designed for real development use |
| **Modular Architecture** | Each component (analyzer, patcher, validator) is independently extensible |
| **Multi-Language Support** | Targets Python, C++, and Java with a language-aware routing layer |
| **Open-Source Positioning** | Built for community use, contribution, and downstream integration |

---

## Architecture Overview

AutoDev is structured as a linear, modular pipeline where each stage has a single responsibility:

```
CLI Input
    │
    ▼
Language Router         → Identifies language, selects appropriate runner
    │
    ▼
Runner                  → Executes the target program and captures output/errors
    │
    ▼
Analyzer                → Parses traces, classifies failure type and location
    │
    ▼
AutoDev Agent           → Orchestrates the repair loop with full context
    │
    ▼
LLM Repair Engine       → Generates patch candidates via Ollama / Groq / Gemini
    │
    ▼
Patch Engine            → Applies selected patches to the source file
    │
    ▼
Output Validator        → Re-runs the patched program and checks for success
    │
    ▼
Retry Manager           → On failure: adjusts strategy, re-prompts, retries
```

Each module communicates through clean interfaces, making it straightforward to swap components, add language support, or integrate new model backends.

---

## How It Works

1. **You point AutoDev at a broken file.**
2. AutoDev runs the program and captures the failure — stack trace, compiler error, or unexpected output.
3. The **Analyzer** identifies the error type and isolates the relevant code region.
4. The **AutoDev Agent** builds a structured repair prompt using the code, error, and any prior context from the **Context Engine**.
5. The **LLM Repair Engine** queries the configured model and receives a patch candidate.
6. The **Patch Engine** applies the fix to the source file.
7. The **Output Validator** re-runs the program. If it passes — done. If it fails — the **Retry Manager** adjusts the approach and tries again.

The result is a fully patched, validated file — with a log of every fix attempt.

---

## Supported Languages

| Language | Status |
|---|---|
| Python | ✅ Supported |
| C++ | ✅ Supported |
| Java | ✅ Supported |
| JavaScript | 🔜 Planned |
| Go | 🔜 Planned |

---

## Installation

**Prerequisites:** Python 3.9+, `pip`, and optionally [Ollama](https://ollama.com/download) for local model execution.

```bash
# 1. Clone the repository
git clone https://github.com/your-username/autodev.git
cd autodev

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the environment template and fill in your keys
cp .env.example .env
```

---

## Model Setup

AutoDev supports three model backends with automatic fallback priority:

### Option 1 — Ollama (Local, Recommended)

```bash
# Install Ollama from https://ollama.com/download, then pull a model:
ollama pull codellama
ollama pull mistral
```

No API keys required. Fully offline.

### Option 2 — Groq (Cloud Fallback)

Sign up at [groq.com](https://groq.com/) and add your key to `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
```

### Option 3 — Gemini (Cloud Fallback)

Sign up at [Google AI Studio](https://aistudio.google.com/) and add your key:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

AutoDev will try Ollama first. If unavailable, it falls back to Groq, then Gemini.

---

## Environment Variables

Create a `.env` file in the project root (use `.env.example` as a template):

```env
# Model backend preference: ollama | groq | gemini | auto
AUTODEV_MODEL_BACKEND=auto

# Ollama settings (if using local model)
OLLAMA_MODEL=codellama
OLLAMA_HOST=http://localhost:11434

# Cloud API keys (used as fallback)
GROQ_API_KEY=
GEMINI_API_KEY=

# Retry configuration
AUTODEV_MAX_RETRIES=3

# Log level: DEBUG | INFO | WARNING | ERROR
AUTODEV_LOG_LEVEL=INFO
```

---

## Configuration

AutoDev reads from `autodev_config.json` for persistent preferences:

```json
{
  "model_backend": "auto",
  "max_retries": 3,
  "languages": ["python", "cpp", "java"],
  "context_memory": true,
  "patch_backup": true,
  "log_level": "INFO"
}
```

| Key | Default | Description |
|---|---|---|
| `model_backend` | `auto` | Preferred LLM backend |
| `max_retries` | `3` | Max patch attempts per bug |
| `context_memory` | `true` | Enable bug pattern memory |
| `patch_backup` | `true` | Back up files before patching |
| `log_level` | `INFO` | Logging verbosity |

---

## Usage

### Basic Usage

```bash
python autodev.py --file path/to/broken_script.py
```

### Specify Language Explicitly

```bash
python autodev.py --file src/main.cpp --lang cpp
```

### Force a Specific Model Backend

```bash
python autodev.py --file App.java --lang java --model groq
```

### Run in Dry Mode (analyze only, no patching)

```bash
python autodev.py --file script.py --dry-run
```

### Verbose Output

```bash
python autodev.py --file script.py --verbose
```

---

## CLI Reference

| Flag | Description |
|---|---|
| `--file <path>` | Path to the source file to debug and repair |
| `--lang <language>` | Language hint: `python`, `cpp`, `java` |
| `--model <backend>` | Force model: `ollama`, `groq`, `gemini`, `auto` |
| `--dry-run` | Analyze and generate patch without applying it |
| `--retries <n>` | Override max retry count for this run |
| `--verbose` | Enable detailed logging output |
| `--no-memory` | Disable context engine for this run |
| `--config <path>` | Path to a custom config file |

---

## Example Output

```
$ python autodev.py --file examples/buggy_sort.py

[AutoDev] Initializing agent...
[AutoDev] Language detected: Python
[AutoDev] Running: examples/buggy_sort.py

[Runner] Execution failed.
[Runner] Error: IndexError: list index out of range (line 14)

[Analyzer] Failure type: RuntimeError — IndexError
[Analyzer] Affected region: lines 12–16
[Analyzer] Root cause hypothesis: off-by-one in loop boundary condition

[Agent] Building repair prompt with context...
[LLM] Querying Ollama (codellama)... done.
[LLM] Patch candidate generated.

[Patcher] Applying patch to examples/buggy_sort.py...
[Patcher] Backup saved: examples/buggy_sort.py.autodev.bak

[Validator] Re-running patched file...
[Validator] ✓ Execution succeeded. Output matches expected behavior.

[AutoDev] ✅ Bug repaired in 1 attempt.
[AutoDev] Patch saved. Context memory updated.
```

---

## Project Structure

```
autodev/
├── autodev.py              # CLI entry point and agent orchestrator
├── analyzer.py             # Error parsing and root cause classification
├── patcher.py              # Patch generation and file modification engine
├── retry_manager.py        # Retry strategy and loop control
├── context_engine.py       # Bug memory and pattern tracking
├── output_validator.py     # Post-patch execution and validation
├── autodev_config.json     # User-facing configuration file
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── .gitignore
├── LICENSE
└── README.md
```

---

## Roadmap

AutoDev is under active development. Planned improvements include:

- [ ] JavaScript and Go language support
- [ ] VS Code extension for in-editor repair
- [ ] Multi-file context awareness for project-level bugs
- [ ] Confidence scoring for patch candidates
- [ ] Diff preview mode before applying patches
- [ ] GitHub Actions integration for CI repair pipelines
- [ ] Web dashboard for repair history and analytics
- [ ] Fine-tuned local model support for code repair
- [ ] PyPI packaging for `pip install autodev`

---

## Contributing

Contributions are welcome and encouraged.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes with clear messages
4. Push to your fork and open a Pull Request

Please read `CONTRIBUTING.md` (coming soon) for code style guidelines and contribution standards. For bugs, feature requests, or questions — open an [issue](https://github.com/your-username/autodev/issues).

---

## License

AutoDev is released under the [MIT License](LICENSE).

---

<div align="center">

**AutoDev** — Because fixing bugs should be automatic.

*Built for developers. Powered by AI. Designed to scale.*

</div>
