"""S2 smoke test: print one reply from the configured local Ollama model.

Usage: python scripts/smoke_model.py [--model NAME]
Exits 1 with a clear message (never hangs) when Ollama is not running.
"""

from __future__ import annotations

import argparse
import sys
import time

from incident_agent.config import Settings
from incident_agent.llm.base import ModelError
from incident_agent.llm.ollama import OllamaChatModel


def main() -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=settings.model_name)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    model = OllamaChatModel(args.model, settings.ollama_base_url, timeout=args.timeout)
    try:
        available = model.list_models()
        print(
            f"[OK] Ollama reachable at {model.base_url}; models: {', '.join(available) or 'none'}"
        )
        if args.model not in available:
            print(f"[FAILED] model {args.model!r} is not pulled. Run: ollama pull {args.model}")
            return 1
        start = time.perf_counter()
        reply = model.chat(
            [{"role": "user", "content": "Reply with exactly: pipeline agent online"}],
            purpose="smoke",
        )
    except ModelError as exc:
        print(f"[FAILED] {exc}")
        return 1
    print(f"[OK] {args.model} replied in {time.perf_counter() - start:.1f}s: {reply['content']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
