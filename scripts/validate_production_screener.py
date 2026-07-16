from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.contracts import CaseSuite  # noqa: E402
from production_screener_validation.pipeline import ValidationPipeline  # noqa: E402


async def run() -> int:
    parser = argparse.ArgumentParser(description="Compare production screener stock sets with approved independent references.")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--case")
    parser.add_argument("--root", type=Path, default=BACKEND / "production_screener_validation" / "data")
    parser.add_argument("--output", type=Path, default=BACKEND / "production_screener_validation" / "reports")
    args = parser.parse_args()
    loaded = CaseSuite.from_json_file(args.cases)
    suite = CaseSuite(loaded.suite_id, tuple(case for case in loaded.cases if not args.case or case.case_id == args.case))
    if not suite.cases:
        raise SystemExit(f"case '{args.case}' was not found")
    result = await ValidationPipeline(args.root).validate_suite(suite, args.output)
    for item in result["results"]:
        print(f"{item['verdict'].upper():20} {item['case_id']}")
        if item["missing_symbols"]: print(f"  Missing: {', '.join(item['missing_symbols'])}")
        if item["unexpected_symbols"]: print(f"  Unexpected: {', '.join(item['unexpected_symbols'])}")
        if item.get("error"): print(f"  Error: {item['error']}")
    print(f"Overall verdict: {result['verdict'].upper()}")
    for name, path in result["paths"].items(): print(f"{name.title()} report: {path}")
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
