import json
import os
import subprocess
import sys
import unittest

import _bootstrap


def rpc(lines):
    env = dict(os.environ)
    env.pop("CUSTOM_STACK_LLM_ENDPOINT", None)
    proc = subprocess.run([sys.executable, "-m", "custom_stack.mcp_server", "--data-dir", str(_bootstrap.ensure_fixtures())],
                          input="\n".join(json.dumps(x) if not isinstance(x, str) else x for x in lines) + "\n",
                          capture_output=True, text=True, cwd=str(_bootstrap.PLATFORM_EVAL), env=env, timeout=120)
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()], proc.stderr


def call(i, name, args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}


class MCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.err = rpc([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            call(3, "list_metrics", {}),
            call(4, "describe_metric", {"metric": "staff_fte"}),
            call(5, "query_metric", {"metric": "staff_headcount", "filters": [
                {"dimension": "state", "op": "eq", "value": "IL"}, {"dimension": "survey_year", "op": "eq", "value": 2023}]}),
            call(6, "query_metric", {"question": "What is the staff headcount?"}),
            call(7, "query_metric", {"question": "Why did FTE fall?"}),
            call(8, "query_metric", {"model": "benchmark_workforce", "metric": "wf_headcount", "dimensions": ["department"]}),
            call(9, "describe_metric", {"metric": "does_not_exist"}),
            {"jsonrpc": "2.0", "id": 10, "method": "no/such"},
            "{not json",
            {"jsonrpc": "2.0", "id": 11, "method": "ping"},
        ])
        cls.by_id = {m.get("id"): m for m in cls.out}

    def payload(self, i):
        return self.by_id[i]["result"]["structuredContent"]

    def test_initialize(self):
        r = self.by_id[1]["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["capabilities"])

    def test_notification_gets_no_response(self):
        self.assertEqual(len([m for m in self.out if m.get("id") is not None]), 11)

    def test_tools_list(self):
        names = [t["name"] for t in self.by_id[2]["result"]["tools"]]
        self.assertEqual(names, ["list_metrics", "describe_metric", "query_metric"])

    def test_list_and_describe(self):
        self.assertGreater(len(self.payload(3)["metrics"]), 20)
        d = self.payload(4)
        self.assertEqual(d["name"], "staff_fte")
        self.assertIn("grain_rule", d)
        self.assertTrue(d["requires_single_time_period"])

    def test_structured_query(self):
        p = self.payload(5)
        self.assertEqual(p["status"], "answer")
        self.assertEqual(p["result"]["rows"], [[293]])
        self.assertIn("SELECT", p["sql"])
        self.assertTrue(p["provenance"]["source_vintages"])

    def test_question_clarify_and_abstain(self):
        self.assertEqual(self.payload(6)["status"], "clarify")
        self.assertEqual(self.payload(7)["status"], "abstain")

    def test_benchmark_model(self):
        self.assertEqual(self.payload(8)["result"]["rows"], [["T1", 1], ["T2", 2]])

    def test_errors(self):
        self.assertTrue(self.by_id[9]["result"]["isError"])
        self.assertEqual(self.by_id[10]["error"]["code"], -32601)
        self.assertEqual(self.by_id[None]["error"]["code"], -32700)
        self.assertEqual(self.by_id[11]["result"], {})


if __name__ == "__main__":
    unittest.main()
