"""
app.py 리팩터링 회귀 테스트.

git HEAD 의 analyze_stocks(min_value, data_version) 와
수정본의 compute_metrics(data_version) + 외부 거래대금 필터가
완전히 같은 결과를 내는지 실제 app.py 소스에서 함수를 추출해 비교한다.
"""
import ast
import sys
from pathlib import Path

import pandas as pd

from conftest_paths import (APP, BUNDLE_FILE, INDEX_FILE, LIST_FILE,
                            PROJECT, SCRATCH, csv_source, has_real_csv)

DATA_FOLDER = csv_source()


def extract(path, names):
    """app.py 를 실행하지 않고 지정한 함수만 꺼내 온다."""
    tree = ast.parse(Path(path).read_text())
    wanted = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    assert len(wanted) == len(names), f"{path}: {[n.name for n in wanted]}"

    # @st.cache_data 데코레이터는 떼어 낸다.
    for n in wanted:
        n.decorator_list = []

    import logging
    ns = {"pd": pd, "DATA_FOLDER": DATA_FOLDER, "BUNDLE_FILE": BUNDLE_FILE,
          "INDEX_FILE": INDEX_FILE, "LIST_FILE": LIST_FILE,
          "logger": logging.getLogger("test")}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), path, "exec"), ns)
    return ns


baseline = extract(PROJECT / "tests" / "baseline" / "app_baseline.py",
                   ["load_stocks", "analyze_stocks"])
current = extract(APP, ["load_stocks", "load_bundle", "compute_metrics"])

metrics, err = current["compute_metrics"]("v")
print("분석 오류 :", err["count"], "/", err["total"], err["codes"])
print(f"compute_metrics 전체 종목 수: {len(metrics)}")

ok = True
for uk in [1, 5, 10, 50, 200, 1000]:
    min_value = uk * 100_000_000

    old = baseline["analyze_stocks"](min_value, "v").reset_index(drop=True)
    new = (
        metrics[metrics["Value"] >= min_value]
        .reset_index(drop=True)
        .copy()
    )

    try:
        pd.testing.assert_frame_equal(old, new, check_like=False)
        status = "OK"
    except AssertionError as e:
        status = f"MISMATCH\n{e}"
        ok = False

    print(f"  최소 거래대금 {uk:>5}억 → old {len(old):>3}종목 / new {len(new):>3}종목 : {status}")

print("\n결과:", "전 구간 동일" if ok else "불일치 발생")
sys.exit(0 if ok else 1)
