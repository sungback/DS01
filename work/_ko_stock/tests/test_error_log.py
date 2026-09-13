"""
compute_metrics 가 종목별 오류를 조용히 넘기지 않고
집계하고 로그로 남기는지 확인한다.

조용히 넘기면 '조건을 만족하는 종목이 없습니다' 와 구분되지 않는다.
"""

from conftest_paths import (APP, BUNDLE_FILE, DATA_FOLDER, INDEX_FILE,
                            LIST_FILE, PROJECT, SCRATCH)

import ast
import logging
import sys

import pandas as pd

logging.basicConfig(level=logging.WARNING, format="LOG> %(message)s")

tree = ast.parse(APP.read_text())
names = ("load_stocks", "load_bundle", "compute_metrics")
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert len(fns) == len(names), [n.name for n in fns]
for n in fns:
    n.decorator_list = []

ns = {
    "pd": pd,
    "DATA_FOLDER": DATA_FOLDER,
    "BUNDLE_FILE": BUNDLE_FILE,
    "INDEX_FILE": INDEX_FILE,
    "LIST_FILE": LIST_FILE,
    "logger": logging.getLogger("app"),
}
exec(compile(ast.Module(body=fns, type_ignores=[]), str(APP), "exec"), ns)

stocks = ns["load_stocks"]("v")
real_groups = ns["load_bundle"]("v")

# 앞쪽 3종목의 표를 망가뜨린다 (Close 컬럼 제거)
victims = [c for c in stocks["Code"] if c in real_groups][:3]
broken = dict(real_groups)
for code in victims:
    broken[code] = real_groups[code].drop(columns=["Close"])

print("일부러 망가뜨린 종목 :", victims)
print("--- 아래 LOG> 줄이 보여야 정상 ---")

# load_bundle 을 가짜로 바꿔치기해 망가진 표를 주입한다
ns["load_bundle"] = lambda data_version: broken

df, err = ns["compute_metrics"]("v")

print("--- 끝 ---")
print()
print("오류 건수 :", err["count"], "/", err["total"])
print("오류 종목 :", err["codes"])

checks = [
    ("오류가 집계된다", err["count"] >= 3),
    ("오류 종목코드가 남는다", all(c in err["codes"] for c in victims[:len(err["codes"])])),
    ("정상 종목은 계속 분석된다", len(df) > 0),
]

print()
ok = True
for label, passed in checks:
    print(f"  {label} : {'통과' if passed else '실패'}")
    ok = ok and passed

print("\n=== 통과 ===" if ok else "\n=== 실패 ===")
sys.exit(0 if ok else 1)
