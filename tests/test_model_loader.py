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

    def _load(self, cfg):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "c.json"
            config.write_text(json.dumps(cfg), encoding="utf-8")
            return load_model(config)

    def test_explicit_config_local_timeout_is_honoured(self):
        # OllamaModel used to re-read the default config and ignore this value.
        orchestrator = self._load({"ollama_model": "m", "local_timeout": 7})
        self.assertEqual(orchestrator.models[0].timeout, 7)

    def test_invalid_numeric_settings_are_rejected(self):
        for key, bad in [("local_timeout", "abc"), ("local_timeout", 0), ("local_timeout", -5),
                         ("local_timeout", True), ("local_timeout", 7.5),
                         ("cloud_timeout", 0), ("model_retries", -1), ("ollama_num_ctx", 10)]:
            with self.subTest(key=key, value=bad):
                with self.assertRaises(ValueError):
                    self._load({"ollama_model": "m", key: bad})

    def test_cloud_timeout_reaches_orchestrator(self):
        orchestrator = self._load({"ollama_model": "m", "cloud_timeout": 9, "model_retries": 2})
        self.assertEqual(orchestrator.timeout, 9)
        self.assertEqual(orchestrator.per_model_retries, 2)

    def test_num_ctx_is_forwarded_to_ollama(self):
        orchestrator = self._load({"ollama_model": "m", "ollama_num_ctx": 8192})
        self.assertEqual(orchestrator.models[0].num_ctx, 8192)


if __name__ == "__main__":
    unittest.main()
