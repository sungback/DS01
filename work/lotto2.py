import streamlit as st
import random
import pandas as pd

st.set_page_config(
    page_title="로또 번호 생성기",
    page_icon="🎲",
    layout="centered"
)

st.title("🎲 로또 번호 생성기")
st.write("로또 번호 5게임을 생성합니다.")
st.write("조건: **6개 번호의 합계가 170 이상 210 이하**인 번호만 출력합니다.")

# 조건값
GAME_COUNT = 5
MIN_SUM = 170
MAX_SUM = 210

if st.button("로또 번호 생성하기"):

    lotto_games = []

    while len(lotto_games) < GAME_COUNT:
        numbers = random.sample(range(1, 46), 6)
        numbers.sort()

        total = sum(numbers)

        if MIN_SUM <= total <= MAX_SUM:
            lotto_games.append(numbers)

    # 표 형태로 정리
    result = []

    for i, numbers in enumerate(lotto_games, start=1):
        result.append({
            "게임": f"{i}게임",
            "번호1": numbers[0],
            "번호2": numbers[1],
            "번호3": numbers[2],
            "번호4": numbers[3],
            "번호5": numbers[4],
            "번호6": numbers[5],
            "합계": sum(numbers)
        })

    df = pd.DataFrame(result)

    st.subheader("생성된 로또 번호")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("번호만 보기")

    for i, numbers in enumerate(lotto_games, start=1):
        st.write(f"**{i}게임** : {numbers} / 합계: {sum(numbers)}")

else:
    st.info("버튼을 누르면 조건에 맞는 로또 번호 5게임이 생성됩니다.")