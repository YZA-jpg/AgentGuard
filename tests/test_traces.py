import json
import unittest

from agentguard.guard import Review
from agentguard.traces import to_events


class TracesTests(unittest.TestCase):
    def test_agentdojo_content_blocks_and_proposed_tool(self):
        messages = (
            {"role": "user", "content": [{"type": "text", "content": "Find the status."}]},
            {"role": "assistant", "content": None, "tool_calls": [{"function": "open", "args": {"id": 2}}]},
            {"role": "tool", "content": [{"type": "text", "content": "Status is pending."}]},
        )
        review = Review(messages, candidate={"function": "close", "args": {"id": 2}})
        events = to_events(review)
        self.assertEqual([e["event_type"] for e in events], ["user", "agent_action", "environment", "agent_action"])
        self.assertEqual(events[2]["text"], "Status is pending.")
        self.assertEqual(json.loads(events[3]["text"]), {"name": "close", "arguments": {"id": 2}})
