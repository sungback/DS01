"""
save_if_changed + data_fingerprint 를 app.py 에서 그대로 꺼내
'파일이 안 바뀌면 지문도 안 바뀐다'를 확인한다.
"""

from conftest_paths import APP, DATA_FOLDER, LIST_FILE, BUNDLE_FILE, PROJECT, SCRATCH
import ast
import hashlib
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd


tmp = Path(tempfile.mkdtemp())

tree = ast.parse(APP.read_text())
fns = [
    n for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name in ("save_if_changed", "data_fingerprint")
]
assert len(fns) == 2

ns = {
    "pd": pd,
    "hashlib": hashlib,
    "logger": logging.getLogger("test"),
    "DATA_FOLDER": tmp,
}
exec(compile(ast.Module(body=fns, type_ignores=[]), str(APP), "exec"), ns)

save_if_changed = ns["save_if_changed"]
data_fingerprint = ns["data_fingerprint"]

df = pd.DataFrame(
    {"Date": ["2026-09-11"], "Name": ["삼성전자"], "Close": [100]}
).set_index("Date")

f = tmp / "TEST.csv"

# 1회차 : 새로 저장
wrote1 = save_if_changed(df, f, index_label="Date")
fp1 = data_fingerprint()

time.sleep(1.1)  # mtime 이 확실히 달라질 수 있는 간격

# 2회차 : 같은 내용 저장 시도
wrote2 = save_if_changed(df, f, index_label="Date")
fp2 = data_fingerprint()

time.sleep(1.1)

# 3회차 : 내용이 달라짐
df2 = pd.DataFrame(
    {"Date": ["2026-09-11", "2026-09-12"],
     "Name": ["삼성전자", "SK하이닉스"],
     "Close": [100, 101]}
).set_index("Date")
wrote3 = save_if_changed(df2, f, index_label="Date")
fp3 = data_fingerprint()

print(f"1회차 저장함 : {wrote1}   지문 {fp1}")
print(f"2회차 저장함 : {wrote2}   지문 {fp2}   (같은 내용)")
print(f"3회차 저장함 : {wrote3}   지문 {fp3}   (내용 변경)")

# to_csv 가 직접 쓴 파일과 바이트 단위로 같아야 한다 (인코딩 확인)
ref = tmp / "REF.csv"
df2.to_csv(ref, index_label="Date")
same_bytes = ref.read_bytes() == f.read_bytes()
print(f"\nto_csv 결과와 바이트 동일 : {same_bytes}")
print(f"한글 UTF-8 로 저장됨 : {'삼성전자'.encode('utf-8') in f.read_bytes()}")

checks = [
    ("새 파일은 저장된다", wrote1 is True),
    ("to_csv 와 바이트 동일", same_bytes),
    ("한글이 UTF-8 로 저장됨", "삼성전자".encode("utf-8") in f.read_bytes()),
    ("같은 내용은 저장하지 않는다", wrote2 is False),
    ("바뀐 내용은 저장한다", wrote3 is True),
    ("파일이 그대로면 지문 유지", fp1 == fp2),
    ("파일이 바뀌면 지문 변경", fp2 != fp3),
]

print()
ok = True
for label, passed in checks:
    print(f"  {label} : {'통과' if passed else '실패'}")
    ok = ok and passed

shutil.rmtree(tmp)

# 기존 대비: 옛 방식은 매 호출마다 값이 달라진다
from datetime import datetime

old1 = datetime.now().strftime("%Y%m%d%H%M%S")
time.sleep(1.1)
old2 = datetime.now().strftime("%Y%m%d%H%M%S")
print(f"\n(참고) 기존 datetime 방식 : {old1} → {old2}  같은가? {old1 == old2}")

sys.exit(0 if ok else 1)
