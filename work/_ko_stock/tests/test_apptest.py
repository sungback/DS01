"""app.py 를 브라우저 없이 실제로 실행해 본다."""
import os
from streamlit.testing.v1 import AppTest

from conftest_paths import APP, DATA_FOLDER, LIST_FILE, BUNDLE_FILE, PROJECT, SCRATCH

APP = str(PROJECT)
os.chdir(APP)
APP = APP + "/app.py"

at = AppTest.from_file(APP, default_timeout=1800).run()

print("예외 :", at.exception)
if at.exception:
    for e in at.exception:
        print(e.value)
    raise SystemExit(1)

print("subheader :", [x.value for x in at.subheader])
print("metric    :", [(x.label, x.value) for x in at.metric])
print("dataframe 개수 :", len(at.dataframe))

# data_editor 가 렌더링되었는지
editors = at.get("data_editor")
print("data_editor 개수 :", len(editors))

# 매매계획 표에서 현재단계 / 매도신호 확인
for i, d in enumerate(at.dataframe):
    cols = list(d.value.columns)
    if "현재단계" in cols:
        print(f"\n매매계획 표(dataframe[{i}]) 행 수 :", len(d.value))
        print("현재단계 :", d.value["현재단계"].value_counts().to_dict())
        print("매도신호 :", d.value["매도신호"].value_counts().to_dict())
        print("손절가 결측 :", int(d.value["손절가"].isna().sum()), "/", len(d.value))

print("\n캡션 수 :", len(at.caption))
print("경고 :", [x.value for x in at.warning])
print("\n=== AppTest 통과 ===")
