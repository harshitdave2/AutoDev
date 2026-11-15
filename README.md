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
- Cross-language benchmark fixtures with exact output oracles.

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

# Repair a program that runs but has incorrect output using a test oracle
python autodev.py run path/to/program.py --expected-output-file path/to/expected_stdout.txt
```

Use `python autodev.py run --help` to see all options. The expected-output file is compared against captured stdout; only line endings and final newlines are normalized.

## Cross-language repair evaluation

The benchmark runner has two deliberately separate modes:

```bash
# No model calls: confirm that every broken fixture reproduces its declared
# failure/wrong output and every reviewed reference implementation matches
# its exact expected output.
python benchmarks/benchmark_runner.py

# Live evaluation: run AutoDev on temporary copies and score the final program
# against the same exact output oracle.
python benchmarks/benchmark_runner.py --repair

# Narrow the live run to one language or one benchmark.
python benchmarks/benchmark_runner.py --repair --language python
python benchmarks/benchmark_runner.py --repair --benchmark type_error

# Use more retries, thorough candidate generation, and a larger per-case timeout.
python benchmarks/benchmark_runner.py --repair --max-retries 5 --thorough --timeout 600
```

A repair only counts as successful when the copied source changes, AutoDev exits successfully, the final program exits successfully, and stdout matches the reference output (line endings/final newlines are normalized; other whitespace is preserved). The original benchmark fixtures are never modified. JSON reports are written under `benchmarks/results/`.

The suite includes runtime failures and a logical-bug case. The logical-bug case is important because the current CLI does not yet accept an expected-output/test oracle; it may correctly remain unrepaired even when its program exits with code zero. Such a result is scored as a failure rather than being counted as an AI repair.

The default preflight does not call an LLM and is suitable for CI. Live repair scores depend on model/provider availability, model version, prompts, and configured retry budgets; compare runs using the same benchmark manifest and settings.

## Configuration

Edit `autodev_config.json` to select model names and tune context and timeout values. Keep provider secrets out of this file; use environment variables or a local `.env` file. The model loader resolves the configuration path relative to the project rather than depending on the current working directory.

## Tests

Unit tests do not call external LLM providers:

```bash
python -m compileall -q agent cli core languages memory models tests benchmarks autodev.py
python -m unittest discover -s tests -v
```

The CI workflow also runs the no-model benchmark preflight with Python, g++, and Java installed. This confirms that the known-broken fixtures and their reference implementations still behave as declared.

## Safety and limitations

- Execution timeouts limit hangs, but do not isolate CPU, memory, filesystem, network, or subprocess access.
- Generated code must be reviewed before being trusted or deployed.
- Heuristic output checks are not a substitute for expected-output tests. For stronger logical-bug detection, provide deterministic test cases or an explicit expected result.
- C++ and Java execution requires external toolchains installed and available on `PATH`.
- Cloud model availability and repair quality depend on provider quotas, model behavior, and the quality of the supplied tests.

## License

MIT
