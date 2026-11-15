import json
import tempfile
import unittest
from pathlib import Path

from models.model_loader import load_model


class ModelLoaderTests(unittest.TestCase):
    def test_loads_local_model_from_explicit_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "autodev_config.json"
            config.write_text(json.dumps({
                "ollama_model": "unit-test-model",
                "api_keys": {},
                "cloud_timeout": 5,
            }), encoding="utf-8")
            orchestrator = load_model(config)
        self.assertEqual(len(orchestrator.models), 1)
        self.assertEqual(orchestrator.models[0].model_name, "unit-test-model")

    def test_missing_config_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_model(missing)

    def test_invalid_json_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "bad.json"
            config.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_model(config)

    def test_empty_provider_configuration_fails_loudly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "empty.json"
            config.write_text(json.dumps({"api_keys": {}}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_model(config)


if __name__ == "__main__":
    unittest.main()
