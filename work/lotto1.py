import streamlit as st
import random
st.title("로또 번호 생성기")
st.markdown("### 합계가 170~210 인것만 사용!")
def gen_lotto():
    while True:
        lotto = sorted( random.sample( range(1, 46), 6 ) )
        if 170 <= sum(lotto) <= 210:
            return lotto
button = st.button("버튼을 클릭하여 로또를 생성해 주세요.")
if button:
    for i in range(1, 6):
        st.markdown(f"#### {i}. 행운의 번호:green[{gen_lotto()}]")