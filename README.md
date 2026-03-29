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