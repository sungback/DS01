"""
일부러 깨진 CSV 를 넣고, compute_metrics 가 조용히 넘기지 않고
오류를 집계·기록하는지 확인한다.
"""
import ast
import logging
import sys
from pathlib import Path

import pandas as pd

from conftest_paths import APP, DATA_FOLDER, LIST_FILE, BUNDLE_FILE, PROJECT, SCRATCH

PROJECT = PROJECT
APP = PROJECT / "app.py"
DATA_FOLDER = PROJECT / "stock_data"

logging.basicConfig(level=logging.WARNING, format="LOG> %(message)s")

tree = ast.parse(APP.read_text())
fns = [n for n in tree.body
       if isinstance(n, ast.FunctionDef) and n.name in ("load_stocks", "compute_metrics")]
for n in fns:
    n.decorator_list = []

ns = {"pd": pd, "DATA_FOLDER": DATA_FOLDER, "logger": logging.getLogger("app")}
exec(compile(ast.Module(body=fns, type_ignores=[]), str(APP), "exec"), ns)

# 깨진 파일 3개를 임시로 만든다 (실제 종목코드 중 앞 3개 사용)
stocks = ns["load_stocks"]("v")
victims = []
backups = {}

for code in stocks["Code"]:
    f = DATA_FOLDER / f"{code}.csv"
    if f.exists() and len(victims) < 3:
        backups[f] = f.read_bytes()
        f.write_text("이건,정상적인,CSV가,아닙니다\n깨진,데이터\n")
        victims.append(code)

print("일부러 깨뜨린 종목 :", victims)
print("--- 아래 LOG> 줄이 보여야 정상 ---")

try:
    df, err = ns["compute_metrics"]("v")
finally:
    for f, data in backups.items():
        f.write_bytes(data)
    print("--- 원본 복구 완료 ---")

print()
print("오류 건수 :", err["count"], "/", err["total"])
print("오류 종목 :", err["codes"])

ok = err["count"] >= 3 and all(c in err["codes"] for c in victims[: len(err["codes"])])
print("\n오류 집계 :", "통과" if err["count"] >= 3 else "실패")
sys.exit(0 if err["count"] >= 3 else 1)
