"""
stock_data/ 폴더 없이 번들만으로 앱이 뜨는지 확인한다.
Streamlit Cloud 는 CSV 를 받지 않으므로 이 상태가 실제 배포 환경이다.
"""

from conftest_paths import APP, BUNDLE_FILE, DATA_FOLDER, INDEX_FILE, LIST_FILE, PROJECT, SCRATCH

import os
import shutil
import sys

for f in (BUNDLE_FILE, INDEX_FILE, LIST_FILE):
    assert f.exists(), f"{f.name} 이 없습니다. Task 3 을 먼저 끝내세요."

# CSV 폴더를 잠시 치운다
moved = None
if DATA_FOLDER.exists():
    moved = SCRATCH / "stock_data_hidden"
    shutil.rmtree(moved, ignore_errors=True)
    shutil.move(str(DATA_FOLDER), str(moved))
    print("stock_data/ 를 잠시 치웠습니다")

try:
    os.chdir(PROJECT)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=1800).run()

    if at.exception:
        for e in at.exception:
            print(e.value)
        raise AssertionError("CSV 없이 앱이 뜨지 않습니다")

    print("예외 없음")
    print("subheader :", [x.value for x in at.subheader])
    print("metric    :", [(x.label, x.value) for x in at.metric])
    assert at.subheader, "화면이 비어 있습니다"

finally:
    if moved is not None:
        shutil.rmtree(DATA_FOLDER, ignore_errors=True)
        shutil.move(str(moved), str(DATA_FOLDER))
        print("stock_data/ 복구 완료")

print("\n=== 통과 ===")
sys.exit(0)
