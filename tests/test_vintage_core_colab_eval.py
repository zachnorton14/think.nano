import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "dev" / "vintage_core_colab"
SPEC = importlib.util.spec_from_file_location("vintage_core_eval", ROOT / "vintage_core_eval.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RegistryTests(unittest.TestCase):
    def test_registries_parse(self):
        models = json.loads((ROOT / "models.json").read_text())["models"]
        bundles = json.loads((ROOT / "bundles.json").read_text())["bundles"]
        self.assertEqual(set(models), {"think-d12-r30", "modern-d24", "gpt1900-d34"})
        self.assertEqual(set(bundles), {"original", "filtered", "restyled"})
        self.assertEqual(
            models["modern-d24"]["runtime"]["revision"],
            "7ac837cff8efc0e85502e2b3a934a35e2d937b8d",
        )
        for model in models.values():
            joined = " ".join(model["allow_patterns"]).lower()
            self.assertNotIn("optimizer", joined)
            self.assertNotIn("optim.", joined)

    def test_notebook_runs_models_into_separate_directories(self):
        notebook = json.loads((ROOT / "Vintage_CORE_Eval.ipynb").read_text())
        code = "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        )
        self.assertIn('RUN_ALL_MODELS = True', code)
        self.assertIn('MODELS_TO_RUN = VALID_MODELS if RUN_ALL_MODELS else [MODEL_ID]', code)
        self.assertIn('output_dir = f"{RESULTS_ROOT}/{model_id}"', code)
        self.assertIn('summary_path.is_file()', code)

    def test_bundle_name_validation(self):
        registry = {"a": {}, "b": {}}
        self.assertEqual(MODULE.parse_bundle_names("a,b", registry), ["a", "b"])
        with self.assertRaises(ValueError):
            MODULE.parse_bundle_names("a,nope", registry)


class PromptFixtureTests(unittest.TestCase):
    """Fixed outputs match nanochat/core_eval.py for all three task types."""

    def test_multiple_choice(self):
        item = {"query": "Sky?", "choices": ["blue", "green"], "gold": 0}
        fewshot = [{"query": "Grass?", "choices": ["red", "green"], "gold": 1}]
        self.assertEqual(
            MODULE.render_prompts_mc(item, " ", fewshot),
            ["Grass? green\n\nSky? blue", "Grass? green\n\nSky? green"],
        )

    def test_schema(self):
        item = {"context_options": ["Alice", "Bob"], "continuation": " won", "gold": 0}
        fewshot = [{"context_options": ["Cat", "Dog"], "continuation": " barked", "gold": 1}]
        self.assertEqual(
            MODULE.render_prompts_schema(item, "", fewshot),
            ["Dog barked\n\nAlice won", "Dog barked\n\nBob won"],
        )

    def test_language_modeling(self):
        item = {"context": "  The answer is  ", "continuation": "yes"}
        self.assertEqual(MODULE.render_prompts_lm(item, " "), ["The answer is", "The answer is yes"])


class ScoringFixtureTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch

    def test_multiple_choice_and_schema_choose_lowest_mean_loss(self):
        torch = self.torch
        inputs = torch.tensor([[0, 1, 2], [0, 1, 3]])
        logits = torch.zeros(2, 3, 5)
        logits[0, 1, 4] = 8.0  # wrong token for choice zero
        logits[1, 1, 3] = 8.0  # correct continuation token for choice one
        for task_type in ("multiple_choice", "schema"):
            self.assertTrue(MODULE.score_core_logits(task_type, logits, inputs, [2, 2], [3, 3], 1))

    def test_language_modeling_requires_every_continuation_token(self):
        torch = self.torch
        inputs = torch.tensor([[0, 1, 2, 3]])
        logits = torch.zeros(1, 4, 5)
        logits[0, 1, 2] = 8.0
        logits[0, 2, 3] = 8.0
        self.assertTrue(MODULE.score_core_logits("language_modeling", logits, inputs, [2], [4]))
        logits[0, 2, 4] = 9.0
        self.assertFalse(MODULE.score_core_logits("language_modeling", logits, inputs, [2], [4]))


class ResultTableTests(unittest.TestCase):
    def test_common_20_is_derived_without_evaluation(self):
        tasks = [f"task_{index}" for index in range(20)]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            for name, extra, score in (("original", True, 0.1), ("filtered", False, 0.2), ("restyled", False, 0.3)):
                centered = {task: score for task in tasks}
                raw = {task: score for task in tasks}
                if extra:
                    centered.update({"extra_a": 0.9, "extra_b": 0.9})
                    raw.update({"extra_a": 0.9, "extra_b": 0.9})
                MODULE.atomic_json(output / f"{name}.json", {
                    "core_metric": sum(centered.values()) / len(centered),
                    "centered_results": centered,
                    "results": raw,
                    "runtime_seconds": 1.0,
                })
            MODULE.write_tables("fixture", ["original", "filtered", "restyled"], output)
            with (output / "summary.csv").open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([round(float(row["common_20_core"]), 1) for row in rows], [0.1, 0.2, 0.3])
            self.assertTrue((output / "task_accuracy.csv").is_file())
            self.assertTrue((output / "task_deltas.csv").is_file())


if __name__ == "__main__":
    unittest.main()
