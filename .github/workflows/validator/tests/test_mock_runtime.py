import asyncio
import json
import sys
import unittest
import warnings
from types import ModuleType
from unittest import mock


VALIDATOR_DIR = __import__("pathlib").Path(__file__).resolve().parents[1]
RUNTIME_DIR = VALIDATOR_DIR / "services/mock_runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from adapters import huggingface_adapter, openai_adapter


class MockRuntimeAdapterTest(unittest.TestCase):
    def setUp(self):
        openai_adapter._models_dev_endpoints.cache_clear()

    def test_endpoint_normalization_patterns_and_validation(self):
        self.assertEqual(
            "https://example.com/v1",
            openai_adapter._normalise_endpoint("HTTPS://EXAMPLE.COM/v1/?ignored=yes"),
        )
        pattern = openai_adapter._endpoint_pattern("https://host/${TOKEN}/v1/")
        self.assertTrue(pattern.fullmatch("https://host/value/v1"))
        with mock.patch.object(
            openai_adapter,
            "_models_dev_endpoints",
            return_value=[(openai_adapter.re.compile(r"https://known/v1"), {"model"})],
        ):
            openai_adapter._validate_endpoint_model("https://known/v1", "model")
            with self.assertRaisesRegex(RuntimeError, "was not found"):
                openai_adapter._validate_endpoint_model("https://unknown/v1", "model")
            with self.assertRaisesRegex(RuntimeError, "not available"):
                openai_adapter._validate_endpoint_model("https://known/v1", "other")

    def test_models_dev_index_uses_provider_and_model_overrides(self):
        payload = {
            "provider": {
                "api": "https://provider/v1",
                "npm": "@ai-sdk/openai-compatible",
                "models": {
                    "one": {"id": "alias"},
                    "two": {"provider": {"api": "https://model/${KEY}/v1", "npm": "@ai-sdk/openai-compatible"}},
                    "ignored": {"provider": {"npm": "other"}},
                },
            }
        }
        response = mock.MagicMock()
        response.__enter__.return_value = response
        with mock.patch.object(openai_adapter, "urlopen", return_value=response), \
             mock.patch.object(openai_adapter.json, "load", return_value=payload):
            endpoints = openai_adapter._models_dev_endpoints()
        indexed = [(pattern.pattern, models) for pattern, models in endpoints]
        self.assertTrue(any({"one", "alias"}.issubset(models) for _, models in indexed))
        self.assertTrue(any("model" in pattern and "two" in models for pattern, models in indexed))

    def test_models_dev_failure_warns_and_disables_validation(self):
        with mock.patch.object(openai_adapter, "urlopen", side_effect=OSError("offline")), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertIsNone(openai_adapter._models_dev_endpoints())
        self.assertTrue(caught)

    def test_prompt_candidates_support_mapping_objects_and_multimodal_content(self):
        class Message:
            content = [{"text": "hello"}, {"content": " world"}]
        self.assertEqual(
            ["system\nhello world", "hello world"],
            openai_adapter._prompt_candidates({"messages": [{"content": "system"}, Message()]}),
        )
        self.assertEqual(["a\nb", "b"], openai_adapter._prompt_candidates({"input": ["a", "b"]}))

    def test_response_selector_prioritizes_prompt_then_sequence_then_default(self):
        selector = openai_adapter._ResponseSelector({
            "prompt_responses": {"known": "matched"},
            "sequence": ["first"],
            "default": "fallback",
        })
        self.assertEqual("matched", selector.next({"prompt": "known"}))
        self.assertEqual("first", selector.next({"prompt": "unknown"}))
        self.assertEqual("fallback", selector.next({"prompt": "again"}))

    def test_openai_install_supports_current_legacy_stream_and_async_apis(self):
        openai = ModuleType("openai")
        with mock.patch.dict(sys.modules, {"openai": openai}), \
             mock.patch.object(openai_adapter, "_validate_endpoint_model"):
            openai_adapter.install({"sequence": ["chat", "completion", "response", "stream", "async"]})
            client = openai.OpenAI(base_url="https://example/v1")
            chat = client.chat.completions.create(model="m", messages=[{"content": "q"}])
            self.assertEqual("chat", chat.choices[0].message.content)
            self.assertEqual("chat", chat.model_dump()["choices"][0]["text"])
            self.assertEqual("completion", client.completions.create(model="m", prompt="q").choices[0].text)
            self.assertEqual("response", client.responses.create(model="m", input="q").output_text)
            chunks = list(openai.ChatCompletion.create(model="m", messages=[], stream=True))
            self.assertEqual("stream", chunks[0].choices[0].delta.content)
            self.assertEqual([], chunks[-1].choices)

            async def invoke():
                async_client = openai.AsyncOpenAI()
                stream = await async_client.chat.completions.create(model="m", messages=[], stream=True)
                return [chunk async for chunk in stream]

            self.assertEqual("async", asyncio.run(invoke())[0].choices[0].delta.content)

    def test_openai_mock_rejects_positional_calls_and_invalid_responses(self):
        with self.assertRaises(TypeError):
            openai_adapter.install([])
        selector = openai_adapter._ResponseSelector({})
        with mock.patch.object(openai_adapter, "_validate_endpoint_model"):
            for api in (
                openai_adapter._ChatCompletions(selector, "url"),
                openai_adapter._Completions(selector, "url"),
                openai_adapter._Responses(selector, "url"),
            ):
                with self.subTest(api=type(api).__name__), self.assertRaises(TypeError):
                    api.create("positional")

    def test_huggingface_install_patches_factories_and_selects_responses(self):
        transformers = ModuleType("transformers")
        transformers.AutoModelForCausalLM = type("AutoModelForCausalLM", (), {})
        transformers.AutoTokenizer = type("AutoTokenizer", (), {})
        responses = {"prompt_responses": {"known": "match"}, "sequence": ["next"], "default": "fallback"}
        with mock.patch.dict(sys.modules, {"transformers": transformers}):
            huggingface_adapter.install(responses)
            model = transformers.AutoModelForCausalLM.from_pretrained("never-download")
            tokenizer = transformers.AutoTokenizer.from_pretrained("never-download")
        self.assertEqual("known", tokenizer.apply_chat_template([{"content": "known"}]))
        batch = tokenizer(["known", "unknown", "other"]).to("cpu")
        generated = model.generate(batch.input_ids)
        self.assertEqual(["match", "next", "fallback"], tokenizer.batch_decode(generated))
        with self.assertRaises(TypeError):
            huggingface_adapter.install([])

    def test_mock_object_attribute_json_and_missing_attribute(self):
        value = openai_adapter._MockObject(nested=openai_adapter._MockObject(value=1))
        self.assertEqual({"nested": {"value": 1}}, value.dict())
        self.assertEqual({"nested": {"value": 1}}, json.loads(value.json()))
        with self.assertRaises(AttributeError):
            _ = value.missing


if __name__ == "__main__":
    unittest.main()
