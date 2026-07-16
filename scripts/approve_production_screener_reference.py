from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.fixture_store import GoldenStore  # noqa: E402


def _format_candidates(store: GoldenStore) -> str:
    candidates = store.list_candidates()
    if not candidates:
        return "No reference candidates exist yet. Generate them first."
    lines = ["Available candidates:"]
    for candidate in candidates:
        expected = ", ".join(candidate.get("expected_symbols") or []) or "none"
        lines.append(
            f"  {candidate['candidate_id']}  case_id={candidate.get('case_id')}  "
            f"status={candidate.get('status')}  expected={expected}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve a reviewed production screener reference candidate without recalculation.")
    parser.add_argument("--candidate", required=True, help="Candidate hash ID or case_id, for example rsi_and_macd")
    parser.add_argument("--approver", required=True)
    parser.add_argument("--root", type=Path, default=BACKEND / "production_screener_validation" / "data")
    args = parser.parse_args()
    store = GoldenStore(args.root)
    try:
        golden_id, path = store.approve(args.candidate, args.approver)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(_format_candidates(store), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(_format_candidates(store), file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Approved golden reference: {golden_id}")
    print(f"Path: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
