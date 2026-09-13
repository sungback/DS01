"""캐시가 실제로 재렌더링을 막는지 측정."""

from conftest_paths import APP, DATA_FOLDER, LIST_FILE, BUNDLE_FILE, PROJECT, SCRATCH
import sys, time, warnings
from pathlib import Path
from streamlit.testing.v1 import AppTest

warnings.filterwarnings("ignore")
import os
os.chdir(PROJECT)


at = AppTest.from_file(str(APP), default_timeout=1800)

t = time.time(); at.run(); t1 = time.time() - t
assert not at.exception, [e.value for e in at.exception]
print(f"① 첫 실행               : {t1:.2f}초")

# 유형만 바꾼다 → 차트는 캐시에서 나와야 한다
t = time.time()
at.sidebar.selectbox[0].select("전체").run()
t2 = time.time() - t
assert not at.exception, [e.value for e in at.exception]
print(f"② 유형 재선택 (캐시 적중) : {t2:.2f}초")

# 차트 기간 변경 → 캐시 미스, 다시 그려야 한다
t = time.time()
at.sidebar.selectbox[1].select(120).run()
t3 = time.time() - t
print(f"③ 차트 기간 변경 (캐시 미스): {t3:.2f}초")

# 다시 원래 기간 → 캐시 적중
t = time.time()
at.sidebar.selectbox[1].select(60).run()
t4 = time.time() - t
print(f"④ 기간 원복 (캐시 적중)    : {t4:.2f}초")

print(f"\n차트 개수: {len([x for x in at.get('image')])}장" if at.get("image") else "")
ok = t2 < t1 and t4 < t3
print("\n캐시 효과 :", "확인됨" if ok else "불명확")
sys.exit(0 if ok else 1)
