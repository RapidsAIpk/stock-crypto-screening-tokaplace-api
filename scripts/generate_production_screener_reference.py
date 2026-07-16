from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.contracts import CaseSuite  # noqa: E402
from production_screener_validation.pipeline import ValidationPipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate unapproved independent reference candidates.")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--case")
    parser.add_argument("--root", type=Path, default=BACKEND / "production_screener_validation" / "data")
    args = parser.parse_args()
    suite = CaseSuite.from_json_file(args.cases)
    pipeline = ValidationPipeline(args.root)
    selected = [case for case in suite.cases if not args.case or case.case_id == args.case]
    if not selected:
        raise SystemExit(f"case '{args.case}' was not found")
    for case in selected:
        candidate_id, path = pipeline.generate_candidate(case)
        print(f"{case.case_id}: candidate={candidate_id} path={path}")
    print("Candidates are not trusted until explicitly approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
