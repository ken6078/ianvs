import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SHARED_RUNTIME = REPO_ROOT / ".github/workflows/validator/services/mock_runtime"
EXAMPLE_RUNTIME = REPO_ROOT / "examples/llm_simple_qa/scripts/mock_runtime"


class MockRuntimeTest(unittest.TestCase):
    @staticmethod
    def _write_openai_stub(temp_dir):
        Path(temp_dir, "openai.py").write_text("", encoding="utf-8")

    def _run_mocked_python(self, code, *pythonpath_entries):
        env = dict(os.environ)
        env["IANVS_LLM_MOCK"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(
            [str(SHARED_RUNTIME), *map(str, pythonpath_entries)]
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_huggingface_factories_are_replaced_in_subprocess(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "transformers.py").write_text(
                "class AutoModelForCausalLM:\n    pass\n\n"
                "class AutoTokenizer:\n    pass\n",
                encoding="utf-8",
            )
            code = """
from transformers import AutoModelForCausalLM, AutoTokenizer
model = AutoModelForCausalLM.from_pretrained('must-not-download')
tokenizer = AutoTokenizer.from_pretrained('must-not-download')
batch = tokenizer(['question'], return_tensors='pt').to('cpu')
generated = model.generate(batch.input_ids)
assert tokenizer.batch_decode(generated) == ['A']
"""

            completed = self._run_mocked_python(
                code, EXAMPLE_RUNTIME, temp_dir
            )

            self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_openai_client_uses_prompt_sequence_and_default_responses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_openai_stub(temp_dir)
            Path(temp_dir, "ianvs_mock_fixture.py").write_text(
                "ADAPTERS = ['openai']\n"
                "RESPONSES = {'openai': {\n"
                "    'prompt_responses': {'system\\nknown': 'matched'},\n"
                "    'sequence': ['first'],\n"
                "    'default': 'fallback',\n"
                "}}\n",
                encoding="utf-8",
            )
            code = """
import re
from adapters import openai_adapter
from openai import OpenAI

openai_adapter._models_dev_endpoints = lambda: [
    (re.compile(r'https://must-not-connect\\.invalid'), {'mock-model'}),
]
client = OpenAI(api_key='must-not-be-used', base_url='https://must-not-connect.invalid')
matched = client.chat.completions.create(
    model='mock-model',
    messages=[
        {'role': 'system', 'content': 'system'},
        {'role': 'user', 'content': 'known'},
    ],
)
assert matched.choices[0].message.content == 'matched'
assert matched['choices'][0]['text'] == 'matched'
assert matched.model_dump()['model'] == 'mock-model'
assert matched.usage.total_tokens == 3

first = client.chat.completions.create(
    model='mock-model', messages=[{'role': 'user', 'content': 'unknown'}]
)
fallback = client.responses.create(model='mock-model', input='unknown again')
assert first.choices[0].message.content == 'first'
assert fallback.output_text == 'fallback'
"""

            completed = self._run_mocked_python(code, temp_dir)

            self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_openai_sync_async_streams_and_legacy_api_are_mocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_openai_stub(temp_dir)
            Path(temp_dir, "ianvs_mock_fixture.py").write_text(
                "ADAPTERS = ['openai']\n"
                "RESPONSES = {'openai': {\n"
                "    'sequence': ['sync stream', 'legacy', 'async stream'],\n"
                "}}\n",
                encoding="utf-8",
            )
            code = """
import asyncio
import re
import openai
from adapters import openai_adapter
from openai import AsyncOpenAI, OpenAI

openai_adapter._models_dev_endpoints = lambda: [
    (re.compile(r'https://api\\.openai\\.com/v1'), {'mock-model'}),
]
client = OpenAI(api_key='must-not-be-used')
chunks = list(client.chat.completions.create(
    model='mock-model',
    messages=[{'role': 'user', 'content': 'one'}],
    stream=True,
    stream_options={'include_usage': True},
))
assert chunks[0].choices[0].delta.content == 'sync stream'
assert chunks[-1].choices == []
assert chunks[-1].usage.completion_tokens == 2

legacy = openai.ChatCompletion.create(
    model='mock-model', messages=[{'role': 'user', 'content': 'two'}]
)
assert legacy.choices[0].message.content == 'legacy'

async def check_async_client():
    client = AsyncOpenAI(api_key='must-not-be-used')
    stream = await client.chat.completions.create(
        model='mock-model',
        messages=[{'role': 'user', 'content': 'three'}],
        stream=True,
    )
    chunks = [chunk async for chunk in stream]
    assert chunks[0].choices[0].delta.content == 'async stream'

asyncio.run(check_async_client())
"""

            completed = self._run_mocked_python(code, temp_dir)

            self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_openai_rejects_unknown_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_openai_stub(temp_dir)
            Path(temp_dir, "ianvs_mock_fixture.py").write_text(
                "ADAPTERS = ['openai']\n"
                "RESPONSES = {'openai': {'default': 'unused'}}\n",
                encoding="utf-8",
            )
            code = """
import re
from adapters import openai_adapter
from openai import OpenAI

openai_adapter._models_dev_endpoints = lambda: [
    (re.compile(r'https://known\\.example/v1'), {'known-model'}),
]
client = OpenAI(base_url='https://missing.example/v1')
try:
    client.chat.completions.create(
        model='known-model', messages=[{'role': 'user', 'content': 'test'}]
    )
except RuntimeError as error:
    assert "endpoint 'https://missing.example/v1' was not found" in str(error)
else:
    raise AssertionError('unknown endpoint was accepted')
"""

            completed = self._run_mocked_python(code, temp_dir)

            self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_openai_rejects_unknown_model_for_known_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self._write_openai_stub(temp_dir)
            Path(temp_dir, "ianvs_mock_fixture.py").write_text(
                "ADAPTERS = ['openai']\n"
                "RESPONSES = {'openai': {'default': 'unused'}}\n",
                encoding="utf-8",
            )
            code = """
import re
from adapters import openai_adapter
from openai import OpenAI

openai_adapter._models_dev_endpoints = lambda: [
    (re.compile(r'https://known\\.example/v1'), {'known-model'}),
]
client = OpenAI(base_url='https://known.example/v1')
try:
    client.chat.completions.create(
        model='missing-model', messages=[{'role': 'user', 'content': 'test'}]
    )
except RuntimeError as error:
    assert "Model 'missing-model' is not available" in str(error)
else:
    raise AssertionError('unknown model was accepted')
"""

            completed = self._run_mocked_python(code, temp_dir)

            self.assertEqual(completed.returncode, 0, completed.stdout)


if __name__ == "__main__":
    unittest.main()
