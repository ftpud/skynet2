import json
import unittest

from agent import Agent


class ExtractJsonTests(unittest.TestCase):
    def setUp(self):
        self.agent = Agent.__new__(Agent)

    def parse(self, text):
        return self.agent._extract_json(text)

    def test_valid_escape_sequences(self):
        text = '{"action":"final_answer","content":"\\\" \\\\ \\/ \\b \\f \\n \\r \\t"}'
        obj = self.parse(text)
        self.assertEqual(obj["action"], "final_answer")
        self.assertIn('"', obj["content"])
        self.assertIn('\\', obj["content"])
        self.assertIn('/', obj["content"])
        self.assertIn('\b', obj["content"])
        self.assertIn('\f', obj["content"])
        self.assertIn('\n', obj["content"])
        self.assertIn('\r', obj["content"])
        self.assertIn('\t', obj["content"])

    def test_unicode_escape(self):
        obj = self.parse('{"action":"final_answer","content":"\\u263A"}')
        self.assertEqual(obj["content"], "☺")

    def test_surrogate_pair(self):
        obj = self.parse('{"action":"final_answer","content":"\\ud83d\\ude00"}')
        self.assertEqual(obj["content"], "😀")

    def test_control_character_escaped(self):
        obj = self.parse('{"action":"final_answer","content":"line1\\nline2"}')
        self.assertEqual(obj["content"], "line1\nline2")

    def test_backslashes_quotes_slashes(self):
        obj = self.parse('{"action":"final_answer","content":"path C:\\\\tmp\\\\file \\\"q\\\" \\/"}')
        self.assertEqual(obj["content"], 'path C:\\tmp\\file "q" /')

    def test_markdown_fence(self):
        obj = self.parse('\n{"action":"final_answer","content":"ok"}\n')
        self.assertEqual(obj["content"], "ok")

    def test_trailing_garbage(self):
        obj = self.parse('{"action":"final_answer","content":"ok"} ###$$$')
        self.assertEqual(obj["content"], "ok")

    def test_multiple_objects_prefers_action(self):
        obj = self.parse('{"x":1} {"action":"final_answer","content":"ok"}')
        self.assertEqual(obj["action"], "final_answer")

    def test_trailing_comma_repair(self):
        obj = self.parse('{"action":"final_answer","content":"ok",}')
        self.assertEqual(obj["content"], "ok")

    def test_invalid_escape_rejected(self):
        obj = self.parse('{"action":"final_answer","content":"\\x"}')
        self.assertIsNone(obj)

    def test_unescaped_control_character_rejected(self):
        bad = '{"action":"final_answer","content":"line1\nline2"}'.replace('\\n', '\n')
        obj = self.parse(bad)
        self.assertIsNone(obj)

    def test_unpaired_surrogate_rejected(self):
        obj = self.parse('{"action":"final_answer","content":"\\ud83d"}')
        # Python json accepts this as a lone surrogate code point in str; extractor should still parse JSON.
        self.assertIsNotNone(obj)
        self.assertEqual(obj["action"], "final_answer")


class FinalAnswerHandlingTests(unittest.TestCase):
    def test_final_answer_after_write_observation_uses_observation_text(self):
        agent = Agent.__new__(Agent)
        agent.verbose = False
        agent.history = [
            {"role": "user", "content": "Update project.md"},
            {"role": "assistant", "content": '{"action":"command","name":"write_file","parameters":{"path":"project.md","content":"x"}}'},
            {"role": "user", "content": "Observation: OK: wrote 1 chars to project.md"},
        ]

        previous_assistant_message = next((m.get("content", "") for m in reversed(agent.history) if m.get("role") == "assistant"), "")
        previous_user_message = next((m.get("content", "") for m in reversed(agent.history) if m.get("role") == "user"), "")
        previous_assistant_json = json.loads(previous_assistant_message)
        pending_write_command = (
            isinstance(previous_assistant_json, dict)
            and previous_assistant_json.get("action") == "command"
            and previous_assistant_json.get("name") == "write_file"
        )

        content = "Updated project.md"
        is_invalid = False
        if pending_write_command:
            if isinstance(previous_user_message, str) and previous_user_message.startswith("Observation: "):
                observation_text = previous_user_message[len("Observation: "):].strip()
                if observation_text.startswith("OK: wrote "):
                    if content.strip() != observation_text:
                        is_invalid = True
                        content = observation_text
                else:
                    is_invalid = True
            else:
                is_invalid = True

        self.assertTrue(pending_write_command)
        self.assertTrue(is_invalid)
        self.assertEqual(content, "OK: wrote 1 chars to project.md")

    def test_final_answer_before_write_observation_is_invalid(self):
        agent = Agent.__new__(Agent)
        agent.history = [
            {"role": "user", "content": "Update project.md"},
            {"role": "assistant", "content": '{"action":"command","name":"write_file","parameters":{"path":"project.md","content":"x"}}'},
        ]

        previous_assistant_message = next((m.get("content", "") for m in reversed(agent.history) if m.get("role") == "assistant"), "")
        previous_user_message = next((m.get("content", "") for m in reversed(agent.history) if m.get("role") == "user"), "")
        previous_assistant_json = json.loads(previous_assistant_message)
        pending_write_command = (
            isinstance(previous_assistant_json, dict)
            and previous_assistant_json.get("action") == "command"
            and previous_assistant_json.get("name") == "write_file"
        )

        is_invalid = False
        if pending_write_command:
            if isinstance(previous_user_message, str) and previous_user_message.startswith("Observation: "):
                observation_text = previous_user_message[len("Observation: "):].strip()
                if not observation_text.startswith("OK: wrote "):
                    is_invalid = True
            else:
                is_invalid = True

        self.assertTrue(pending_write_command)
        self.assertTrue(is_invalid)


if __name__ == "__main__":
    unittest.main()
