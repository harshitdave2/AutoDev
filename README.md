# AutoDev — Autonomous AI Debugging Agent

AutoDev is a command-line debugging assistant for Python, C++, and Java. It executes a target program, analyzes runtime/compiler failures or suspicious output, asks configured language models for repair candidates, validates patches, applies a candidate, and reruns the program.

> **Important:** AutoDev currently executes target programs and generated patches with the permissions of the current user. It is not a security sandbox. Only run it against code you trust, preferably inside a disposable virtual machine or container.

## Capabilities

- Runtime and compiler error analysis for Python, C++, and Java.
- Local model support through Ollama, with optional Groq and Gemini providers.
- Candidate normalization, patch validation, retry strategies, and repair memory.
- Full-file replacement and optional function-level patching.
- Dry-run mode for reviewing a proposed patch without changing the target source.
- Bounded execution time for Python, C++, and Java test runs.
- Benchmark fixtures and offline unit tests.

## Architecture

```text
CLI
 └─ RetryManager
     ├─ LanguageDetector / LanguageRouter
     ├─ Language Executor (Python / C++ / Java)
     ├─ Analyzer + BugLocalizer + ContextEngine
     ├─ AutoDevAgent
     │   └─ ModelOrchestrator (Ollama / Groq / Gemini)
     ├─ ResponseNormalizer + PatchValidator
     ├─ Patch / FunctionPatchMerger
     ├─ Regression + Behavior checks
     └─ Re-execution and rollback
```

## Requirements

- Python 3.10 or newer.
- Ollama for local model inference (recommended).
- A C++17 compiler named `g++` for C++ projects.
- A JDK providing both `javac` and `java` for Java projects.
- Groq and Gemini API keys only when using those cloud providers.

## Installation

```bash
git clone https://github.com/harshitdave2/AutoDev.git
cd AutoDev

python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install and start Ollama, then pull the model configured in `autodev_config.json`:

```bash
ollama pull deepseek-coder:6.7b
```

The default configuration uses Ollama. To enable cloud fallback, set `GROQ_API_KEY` and/or `GEMINI_API_KEY` in the environment or in a local `.env` file in the repository root. Never commit real API keys.

## Usage

```bash
# Repair a Python program
python autodev.py run examples/broken_python.py

# Repair C++ or Java (requires the relevant compiler/runtime)
python autodev.py run examples/broken_cpp.cpp
python autodev.py run examples/broken_java.java

# Preview a proposed repair without modifying the source
python autodev.py run examples/broken_python.py --dry-run

# Use more thorough multi-candidate repair
python autodev.py run examples/broken_python.py --no-fast

# Use function-level patching
python autodev.py run examples/broken_python.py --mode function

# Adjust the retry budget
python autodev.py run examples/broken_python.py --max-retries 5
```

Use `python autodev.py run --help` to see all options.

## Configuration

Edit `autodev_config.json` to select model names and tune context and timeout values. Keep provider secrets out of this file; use environment variables or a local `.env` file. The model loader resolves the configuration path relative to the project rather than depending on the current working directory.

## Tests

Unit tests do not call external LLM providers:

```bash
python -m compileall -q agent cli core languages memory models tests autodev.py
python -m unittest discover -s tests -v
```

GitHub Actions runs the same compile and unit-test checks on pushes to the maintenance branch and on pull requests targeting `main`.

## Safety and limitations

- Execution timeouts limit hangs, but do not isolate CPU, memory, filesystem, network, or subprocess access.
- Generated code must be reviewed before being trusted or deployed.
- Heuristic output checks are not a substitute for expected-output tests. For stronger logical-bug detection, provide deterministic test cases or an explicit expected result.
- C++ and Java execution requires external toolchains installed and available on `PATH`.
- Cloud model availability and repair quality depend on provider quotas, model behavior, and the quality of the supplied tests.

## License

MIT
