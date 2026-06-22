import unittest
from types import SimpleNamespace

from voice_assistant.openai_client import HistoryMessage, OpenAIClient


class _FakeResponse:
    ok = True
    status_code = 200
    text = ""
    content = b""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class _FakeSession:
    def __init__(self, bodies):
        self._bodies = list(bodies)
        self.posts = []

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        return _FakeResponse(self._bodies.pop(0))


def _config():
    return SimpleNamespace(
        chat_model="test-model",
        system_prompt="prompt",
        request_timeout_seconds=30,
    )


class OpenAIClientTest(unittest.TestCase):
    def test_reply_executes_function_call_and_sends_tool_output(self) -> None:
        client = OpenAIClient("key", _config())
        client.session = _FakeSession(
            [
                {
                    "output": [
                        {"type": "reasoning", "id": "rs_1", "summary": []},
                        {
                            "type": "function_call",
                            "id": "fc_1",
                            "call_id": "call_1",
                            "name": "get_current_datetime",
                            "arguments": "{}",
                        },
                    ]
                },
                {"output_text": "Son las 14:30."},
            ]
        )

        text = client.reply("Que hora es?", [HistoryMessage("assistant", "Hola")])

        self.assertEqual(text, "Son las 14:30.")
        self.assertEqual(len(client.session.posts), 2)
        first_payload = client.session.posts[0][1]["json"]
        second_payload = client.session.posts[1][1]["json"]
        self.assertTrue(first_payload["tools"])
        self.assertEqual(second_payload["input"][0], {"role": "assistant", "content": "Hola"})
        self.assertEqual(second_payload["input"][2]["type"], "reasoning")
        self.assertEqual(second_payload["input"][3]["type"], "function_call")
        self.assertEqual(second_payload["input"][4]["type"], "function_call_output")
        self.assertEqual(second_payload["input"][4]["call_id"], "call_1")
        self.assertIn('"now"', second_payload["input"][4]["output"])


if __name__ == "__main__":
    unittest.main()
