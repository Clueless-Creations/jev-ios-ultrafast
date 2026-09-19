import unittest

from jev_ios.model_profiles import DEFAULT_BASELINE_MODEL, resolve_profile


class ModelProfileTests(unittest.TestCase):
    def test_nano_and_unknown_models_keep_legacy_request_settings(self):
        for model in (DEFAULT_BASELINE_MODEL, "example/compatible-model"):
            with self.subTest(model=model):
                profile = resolve_profile(model)
                self.assertEqual(profile.model, model)
                self.assertEqual((profile.reasoning_effort, profile.temperature, profile.max_output_tokens), ("none", 0, 128))

    def test_astra_variants_remain_distinct_and_require_reasoning(self):
        for name, model in (("astra-standard", "openai/gpt-6-astra"), ("astra-fast", "openai/gpt-6-astra-fast")):
            with self.subTest(model=model):
                profile = resolve_profile(model)
                self.assertEqual(profile.model, model)
                self.assertEqual(profile.name, name)
                self.assertEqual((profile.reasoning_effort, profile.temperature, profile.max_output_tokens), ("low", None, 1024))
                self.assertEqual(profile.metadata()["temperature_policy"], "omitted")
                for effort in (None, "none", "minimal"):
                    with self.assertRaises(ValueError):
                        resolve_profile(model, reasoning_effort=effort)

    def test_output_override_is_bounded_and_does_not_mutate_defaults(self):
        model = "openai/gpt-6-astra"
        for limit in (1, 2048, 8192):
            self.assertEqual(resolve_profile(model, max_output_tokens=limit).max_output_tokens, limit)
        self.assertEqual(resolve_profile(model).max_output_tokens, 1024)
        for limit in (0, -1, 8193, True, 128.0, "1024"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                resolve_profile(model, max_output_tokens=limit)
