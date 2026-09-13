"""전체 테스트 실행기. 모두 통과하면 종료코드 0."""

import subprocess
import sys
from pathlib import Path

TESTS = [
    "test_bundle_build.py",
    "test_bundle_read.py",
    "test_prepare_bundle.py",
    "test_metrics_equiv.py",
    "test_sell_stage.py",
    "test_error_log.py",
    "test_fingerprint.py",
    "test_font.py",
    "test_chart_cache.py",
    "test_apptest.py",
]

HERE = Path(__file__).resolve().parent


def main():
    failed = []

    for name in TESTS:
        proc = subprocess.run(
            [sys.executable, str(HERE / name)],
            cwd=HERE,
            capture_output=True,
            text=True,
        )
        mark = "통과" if proc.returncode == 0 else "실패"
        print(f"  {name:<26} {mark}")

        if proc.returncode != 0:
            failed.append(name)
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:])

    print()
    if failed:
        print("실패:", ", ".join(failed))
        return 1

    print(f"전체 {len(TESTS)}종 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
