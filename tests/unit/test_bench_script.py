import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bench_tools.py"


def _load():
    spec = importlib.util.spec_from_file_location("bench_tools", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bench_tools"] = mod  # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


def _call(name, args):
    return {"tool_calls": [{"function": {"name": name, "arguments": args}}]}


def test_bench_scoring_rules():
    bench = _load()
    ok = json.dumps({"pipeline": "p", "pattern": "ERROR"})
    assert bench.check(_call("search_logs", ok), "search_logs") == "pass"
    assert bench.check(_call("search_logs", "{bad json"), "search_logs") == "malformed"
    assert bench.check(_call("search_logs", json.dumps({"pipeline": "p"})), "search_logs") == (
        "malformed"
    )
    assert bench.check(_call("fetch_log_window", ok), "search_logs") == "wrong_tool"
    assert bench.check({"content": "the error is..."}, "search_logs") == "malformed"
