"""전체 테스트 실행기. 모두 통과하면 종료코드 0.

실행: /Users/back/miniforge3/bin/python3 tests/run_all.py
(streamlit · mplfinance 가 설치된 환경이어야 app.py 를 import 할 수 있다)
"""

import os
import subprocess
import sys
from pathlib import Path

TESTS = [
    "test_indicators.py",
    "test_score.py",
    "test_tick_size.py",
    "test_trade_plan.py",
    "test_advice.py",
    "test_screen_entry.py",
    "test_cache_freshness.py",
    "test_pipeline_offline.py",
]

HERE = Path(__file__).resolve().parent


def main():
    failed = []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    for name in TESTS:
        proc = subprocess.run(
            [sys.executable, str(HERE / name)],
            cwd=HERE,
            capture_output=True,
            text=True,
            env=env,
        )
        mark = "통과" if proc.returncode == 0 else "실패"
        summary = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        print(f"  {name:<26} {mark}  {summary}")

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
