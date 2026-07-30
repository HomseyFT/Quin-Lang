"""Regenerate tests/golden/*.out from the current compiler behavior.

Run with `python3 -m tests.update_golden` from the repo root. This records
whatever the compiler does today, so review the resulting diff before
committing: it cannot tell a fix from a regression.
"""

from tests.harness import EXAMPLES_PATH, GOLDEN_PATH, run_file


def main() -> int:
    GOLDEN_PATH.mkdir(parents=True, exist_ok=True)
    examples = sorted(EXAMPLES_PATH.glob("*.ql"))
    if not examples:
        print(f"No examples found in {EXAMPLES_PATH}")
        return 1

    changed = 0
    for path in examples:
        golden = GOLDEN_PATH / f"{path.stem}.out"
        before = golden.read_text(encoding="utf-8") if golden.exists() else None
        try:
            actual = run_file(path).stdout
        except Exception as e:  # noqa: BLE001 - report and keep going
            print(f"  FAIL  {path.name}: {type(e).__name__}: {e}")
            continue
        if before == actual:
            print(f"  same  {path.name}")
            continue
        golden.write_text(actual, encoding="utf-8")
        changed += 1
        print(f"{'  NEW ' if before is None else 'UPDATE'}  {path.name}")

    # Drop goldens whose example is gone, so the orphan check stays green.
    stems = {p.stem for p in examples}
    for stale in sorted(GOLDEN_PATH.glob("*.out")):
        if stale.stem not in stems:
            stale.unlink()
            changed += 1
            print(f"REMOVE  {stale.name}")

    print(f"\n{changed} file(s) changed in {GOLDEN_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
