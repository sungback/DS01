"""
data_fingerprint 가 '파일이 안 바뀌면 같은 값' 을 지키는지 확인한다.

이 성질이 깨지면 앱이 1시간마다 계산 결과 캐시를 통째로 버린다.
"""

from conftest_paths import APP, SCRATCH

import ast
import hashlib
import logging
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

work = SCRATCH / "fingerprint_work"
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)

BUNDLE = work / "stock_data.parquet"
INDEX = work / "kospi_index.parquet"
LIST = work / "kospi_list.parquet"

tree = ast.parse(APP.read_text())
names = ("save_bundle", "data_fingerprint")
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert len(fns) == len(names), [n.name for n in fns]
for n in fns:
    n.decorator_list = []

ns = {
    "pd": pd,
    "hashlib": hashlib,
    "logger": logging.getLogger("test"),
    "BUNDLE_FILE": BUNDLE,
    "INDEX_FILE": INDEX,
    "LIST_FILE": LIST,
}
exec(compile(ast.Module(body=fns, type_ignores=[]), str(APP), "exec"), ns)

save_bundle = ns["save_bundle"]
data_fingerprint = ns["data_fingerprint"]

# 파일이 하나도 없을 때도 값을 돌려줘야 한다
fp_empty = data_fingerprint()
print(f"파일 없음        지문 {fp_empty}")

df = pd.DataFrame({
    "Code": ["005930", "005930"],
    "Date": pd.to_datetime(["2026-09-10", "2026-09-11"]),
    "Open": [100, 101], "High": [102, 103], "Low": [99, 100],
    "Close": [101, 102], "Volume": [10, 11], "Change": [0.01, 0.01],
})

save_bundle(df, BUNDLE)
save_bundle(df.head(1), INDEX)
save_bundle(pd.DataFrame({"Code": ["005930"], "Name": ["삼성전자"]}), LIST)
fp1 = data_fingerprint()
print(f"번들 생성 후     지문 {fp1}")

# ① 아무것도 건드리지 않으면 지문이 같아야 한다
time.sleep(1.1)
fp2 = data_fingerprint()
print(f"그대로 다시 확인 지문 {fp2}")

# ② 내용이 바뀌면 지문도 바뀌어야 한다
time.sleep(1.1)
bigger = pd.concat([df, df.tail(1).assign(Date=pd.to_datetime(["2026-09-12"]))])
save_bundle(bigger, BUNDLE)
fp3 = data_fingerprint()
print(f"번들 변경 후     지문 {fp3}")

checks = [
    ("파일이 없어도 값을 돌려준다", isinstance(fp_empty, str) and len(fp_empty) == 12),
    ("번들이 생기면 지문이 달라진다", fp_empty != fp1),
    ("파일이 그대로면 지문 유지", fp1 == fp2),
    ("파일이 바뀌면 지문 변경", fp2 != fp3),
]

print()
ok = True
for label, passed in checks:
    print(f"  {label} : {'통과' if passed else '실패'}")
    ok = ok and passed

shutil.rmtree(work, ignore_errors=True)

print("\n=== 통과 ===" if ok else "\n=== 실패 ===")
sys.exit(0 if ok else 1)
