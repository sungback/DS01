"""
보유 종목이 파일에 저장되고 다시 읽히는지 확인한다.

세션에만 담아 두면 새로고침할 때 전부 사라진다.
입력한 매수가가 남지 않던 원인이었다.
"""

from conftest_paths import APP, SCRATCH

import ast
import json
import logging
import shutil
import sys

import pandas as pd

work = SCRATCH / "positions_work"
shutil.rmtree(work, ignore_errors=True)
work.mkdir(parents=True)

POSITIONS_FILE = work / "positions.json"

tree = ast.parse(APP.read_text())
names = ("load_positions", "save_positions")
fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert len(fns) == len(names), [n.name for n in fns]

ns = {
    "json": json,
    "pd": pd,
    "logger": logging.getLogger("test"),
    "POSITIONS_FILE": POSITIONS_FILE,
}
exec(compile(ast.Module(body=fns, type_ignores=[]), str(APP), "exec"), ns)

load_positions = ns["load_positions"]
save_positions = ns["save_positions"]

checks = []

# ① 파일이 없으면 빈 값
checks.append(("파일이 없으면 빈 값", load_positions() == {}))

# ② 저장하면 그대로 읽힌다 (= 새로고침해도 남는다)
data = {
    "105560": {"매수가": 160000.0, "손절가": None},
    "005930": {"매수가": 70000.0, "손절가": 65000.0},
}
save_positions(data)
checks.append(("저장한 값이 그대로 읽힌다", load_positions() == data))
checks.append(("파일이 실제로 만들어진다", POSITIONS_FILE.exists()))

# ③ 지우면 파일에도 반영된다
save_positions({})
checks.append(("빈 값으로 저장하면 빈 값", load_positions() == {}))

# ④ 한글 종목명이 깨지지 않는다
save_positions({"005930": {"매수가": 70000.0, "손절가": None}})
raw = POSITIONS_FILE.read_text(encoding="utf-8")
checks.append(("한글 키를 그대로 쓴다", "매수가" in raw))

# ⑤ 깨진 파일이어도 앱이 죽지 않는다
POSITIONS_FILE.write_text("이건 JSON 이 아닙니다", encoding="utf-8")
checks.append(("깨진 파일이면 빈 값", load_positions() == {}))

# ⑥ 이상한 값은 걸러 낸다
POSITIONS_FILE.write_text(json.dumps({
    "111111": {"매수가": "글자"},
    "222222": {"매수가": -5},
    "333333": {"매수가": 1000, "손절가": "이상함"},
    "444444": "사전이 아님",
}), encoding="utf-8")
loaded = load_positions()
checks.append(("숫자가 아닌 매수가는 버린다", "111111" not in loaded))
checks.append(("0 이하 매수가는 버린다", "222222" not in loaded))
checks.append(("이상한 손절가는 None 으로", loaded.get("333333", {}).get("손절가") is None))
checks.append(("사전이 아닌 항목은 버린다", "444444" not in loaded))

print()
ok = True
for label, passed in checks:
    print(f"  {label} : {'통과' if passed else '실패'}")
    ok = ok and passed

shutil.rmtree(work, ignore_errors=True)
print("\n=== 통과 ===" if ok else "\n=== 실패 ===")
sys.exit(0 if ok else 1)
