<<<<<<< HEAD
# AutoDev 🚀

AutoDev is an autonomous AI-powered debugging agent that:

- Executes Python scripts
- Detects crashes
- Extracts context
- Asks a local AI model for a fix
- Applies the patch
- Re-runs automatically

## Default Model
qwen2.5-coder (via Ollama)

## Run (Coming Soon)
python autodev.py run test_scripts/zero_div.py

## Architecture
Runner → Analyzer → Agent → Patcher → Retry Loop
=======
# AutoDev
AutoDev — Autonomous Developer Agent is an AI-powered debugging system that automatically detects, analyzes, and repairs bugs in Python, C++, and Java programs. It executes failing code, diagnoses errors, generates AI-based patches, and validates fixes through automated testing using local or cloud LLMs.
>>>>>>> 855fa6d0fedc84e48c8b0a79e2fabbfec607d277
