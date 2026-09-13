"""
to_price 가 표에서 들어온 글자를 가격으로 바꾸는지 확인한다.

보유 종목 입력 표는 글자 칸이다.
숫자 칸으로 두면 값이 없을 때 Streamlit 이 "None" 을 그려서
입력하는 칸으로 보이지 않기 때문이다.
따라서 표에서 오는 값은 항상 글자이고, 이 함수가 숫자로 바꾼다.
"""

from conftest_paths import APP

import ast
import sys

import pandas as pd

tree = ast.parse(APP.read_text())
fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "to_price"]
assert fn, "to_price 를 찾지 못했습니다"

ns = {"pd": pd}
exec(compile(ast.Module(body=fn, type_ignores=[]), str(APP), "exec"), ns)
to_price = ns["to_price"]

cases = [
    # 비어 있음 → 미보유
    ("", None),
    ("   ", None),
    (None, None),
    (float("nan"), None),
    # 사람이 실제로 칠 법한 형태
    ("170000", 170000.0),
    ("170,000", 170000.0),
    ("170,000원", 170000.0),
    (" 170,000 ", 170000.0),
    # 숫자로 들어와도 받는다
    (170000, 170000.0),
    (170000.0, 170000.0),
    # 가격이 될 수 없는 값 → 미보유
    ("abc", None),
    ("0", None),
    ("-5", None),
    (0, None),
]

ok = True
for raw, want in cases:
    got = to_price(raw)
    mark = "OK" if got == want else f"FAIL (기대 {want!r})"
    if got != want:
        ok = False
    print(f"  {raw!r:>14} → {got!r:>10}  {mark}")

print("\n=== 통과 ===" if ok else "\n=== 실패 ===")
sys.exit(0 if ok else 1)
