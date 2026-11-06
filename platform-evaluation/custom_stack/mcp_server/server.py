"""Minimal stdio MCP server (JSON-RPC 2.0, newline-delimited, stdlib + duckdb).

Exposes governed metrics to any MCP-capable LLM client:
  list_metrics     - metric catalog (name, label, unit, definition)
  describe_metric  - full definition: grain rule, dimensions, values, constraints
  query_metric     - structured plan OR a natural-language `question`; returns
                     status (answer/clarify/abstain), SQL, rows and provenance

The client model never writes SQL. Every query goes through the same compiler
and grain rules as the CLI and the evaluation harness.

Run:   python -m custom_stack.mcp_server [--data-dir DIR]   (from platform-evaluation/)
Client config example (Claude Desktop / any MCP client):
  {"command": "python", "args": ["-m", "custom_stack.mcp_server"],
   "cwd": "<repo>/platform-evaluation", "env": {"CUSTOM_STACK_LAKE_DIR": "<repo>/platform-evaluation/data/lake/contract"}}
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback

from ..nl2sql.planner import Planner, answer, provenance
from ..semantic.compile_duckdb import NeedsClarification, PlanError, Unsupported, compile_plan
from ..semantic.engine import DataUnavailable, Engine
from ..semantic.model import load_all

SERVER_NAME = "hr-governed-metrics"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
MAX_ROWS = 1000

_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "dimension": {"type": "string"},
        "op": {"type": "string", "enum": ["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "between", "latest"]},
        "value": {},
        "values": {"type": "array"},
    },
    "required": ["dimension", "op"],
}

TOOLS = [
    {
        "name": "list_metrics",
        "description": "List governed HR/workforce metrics with their definitions and units. Call this first.",
        "inputSchema": {"type": "object", "properties": {
            "model": {"type": "string", "description": "Semantic model name; omit for all models."}}},
    },
    {
        "name": "describe_metric",
        "description": "Full definition of one metric: grain rule, additivity, allowed dimensions and values, "
                       "time dimensions and mandatory constraints.",
        "inputSchema": {"type": "object", "properties": {
            "metric": {"type": "string"}, "model": {"type": "string"}}, "required": ["metric"]},
    },
    {
        "name": "query_metric",
        "description": "Run a governed metric query. Pass EITHER a structured plan (metric, dimensions, filters, "
                       "order_by, limit) OR a natural-language `question`. Returns status answer/clarify/abstain. "
                       "If status is clarify, ask the user the returned question; do not guess.",
        "inputSchema": {"type": "object", "properties": {
            "model": {"type": "string", "default": "hr_public"},
            "question": {"type": "string"},
            "metric": {"type": "string"},
            "dimensions": {"type": "array", "items": {"type": "string"}},
            "filters": {"type": "array", "items": _FILTER_SCHEMA},
            "order_by": {"type": "object", "properties": {
                "field": {"type": "string"}, "direction": {"type": "string", "enum": ["asc", "desc"]}}},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS},
        }},
    },
]


class MetricsServer:
    def __init__(self, data_dirs: dict[str, str] | None = None):
        self.models = load_all()
        self.data_dirs = data_dirs or {}
        self.engines: dict[str, Engine] = {}
        self.planners = {n: Planner(m) for n, m in self.models.items()}

    def engine(self, model: str) -> Engine:
        if model not in self.engines:
            self.engines[model] = Engine(self.models[model], self.data_dirs.get(model))
        return self.engines[model]

    def _model(self, name: str | None) -> str:
        name = name or "hr_public"
        if name not in self.models:
            raise ValueError(f"unknown model {name!r}; available: {sorted(self.models)}")
        return name

    # ------------------------------------------------------------- tools
    def list_metrics(self, args: dict) -> dict:
        names = [self._model(args["model"])] if args.get("model") else sorted(self.models)
        out = []
        for n in names:
            m = self.models[n]
            for mn, met in m.metrics.items():
                out.append({"model": n, "metric": mn, "label": met.label, "unit": met.unit,
                            "description": met.description, "spec_status": m.status})
        return {"metrics": out}

    def describe_metric(self, args: dict) -> dict:
        mname = args.get("metric")
        if args.get("model"):
            model = self._model(args["model"])
        else:
            hits = [n for n, m in self.models.items() if mname in m.metrics]
            if not hits:
                raise ValueError(f"unknown metric {mname!r}")
            model = hits[0]
        m = self.models[model]
        if mname not in m.metrics:
            raise ValueError(f"unknown metric {mname!r} in model {model}")
        return {"model": model, "spec_sha256": m.sha256, **m.describe_metric(mname)}

    def query_metric(self, args: dict) -> dict:
        model_name = self._model(args.get("model"))
        model = self.models[model_name]
        if args.get("question"):
            res = answer(self.planners[model_name], self.engine(model_name), str(args["question"])[:2000])
            out = res.to_dict()
        else:
            plan = {k: args[k] for k in ("metric", "dimensions", "filters", "order_by", "limit") if k in args}
            out = {"status": "abstain", "model": model_name, "planner": "structured", "plan": plan}
            try:
                compiled = compile_plan(model, plan)
                eng = self.engine(model_name)
                result = eng.execute(compiled)
                prov = provenance(model, compiled)
                prov["source_vintages"] = eng.source_vintages(compiled)
                prov["join_coverage"] = eng.join_coverage(compiled)
                out.update(status="answer", plan=compiled.plan, sql=compiled.sql, result=result,
                           assumptions=compiled.assumptions, provenance=prov)
            except NeedsClarification as c:
                out.update(status="clarify", clarification={"kind": c.kind, "question": c.question,
                                                             "options": c.options, "dimension": c.dimension})
            except Unsupported as u:
                out["abstention"] = {"rule": "unsupported", "reason": u.reason}
            except PlanError as p:
                out["abstention"] = {"rule": "invalid_plan", "reason": str(p)}
            except DataUnavailable as d:
                out["abstention"] = {"rule": "data_unavailable", "reason": str(d)}
        if out.get("result") and len(out["result"]["rows"]) > MAX_ROWS:
            out["result"]["rows"] = out["result"]["rows"][:MAX_ROWS]
            out["result"]["truncated"] = True
        return out

    # ---------------------------------------------------------- protocol
    def handle(self, msg: dict) -> dict | None:
        mid = msg.get("id")
        method = msg.get("method")
        is_notification = "id" not in msg
        try:
            if method == "initialize":
                requested = (msg.get("params") or {}).get("protocolVersion")
                version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
                result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                          "instructions": "Governed HR metrics. Use list_metrics/describe_metric, then query_metric. "
                                          "Relay clarify questions to the user; never compute metrics yourself."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = msg.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                fn = {"list_metrics": self.list_metrics, "describe_metric": self.describe_metric,
                      "query_metric": self.query_metric}.get(name)
                if fn is None:
                    return None if is_notification else _error(mid, -32602, f"unknown tool {name!r}")
                try:
                    payload = fn(args)
                    result = {"content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                              "structuredContent": payload, "isError": False}
                except Exception as exc:  # tool errors are reported in-band per MCP
                    result = {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
            elif method and method.startswith("notifications/"):
                return None
            else:
                return None if is_notification else _error(mid, -32601, f"method not found: {method}")
        except Exception as exc:  # pragma: no cover
            traceback.print_exc(file=sys.stderr)
            return None if is_notification else _error(mid, -32603, str(exc))
        return None if is_notification else {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, stdin=sys.stdin, stdout=sys.stdout) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                resp = _error(None, -32700, f"parse error: {exc}")
            else:
                if isinstance(msg, list):  # batch (older protocol revisions)
                    resps = [r for r in (self.handle(m) for m in msg) if r is not None]
                    resp = resps or None
                else:
                    resp = self.handle(msg)
            if resp is not None:
                stdout.write(json.dumps(resp, default=str) + "\n")
                stdout.flush()


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="custom_stack.mcp_server")
    ap.add_argument("--data-dir", help="contract-layer Parquet directory for hr_public (default: env or spec default)")
    a = ap.parse_args(argv)
    MetricsServer({"hr_public": a.data_dir} if a.data_dir else None).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
