# pip install streamlit finance-datareader plotly pandas
# streamlit run stock.py

import streamlit as st
import FinanceDataReader as fdr
import requests
import urllib3
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

# ==========================================
# 1. SSL 보안 우회 패치
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
original_request = requests.Session.request

def patched_request(self, method, url, *args, **kwargs):
    kwargs['verify'] = False
    return original_request(self, method, url, *args, **kwargs)

requests.Session.request = patched_request

# ==========================================
# 2. 데이터 로직
# ==========================================
@st.cache_data(ttl=3600)
def get_stock_data(ticker, start_date, end_date):
    try:
        df = fdr.DataReader(ticker, start_date, end_date)
        return df
    except Exception as e:
        return None

@st.cache_data
def get_stock_list():
    df = fdr.StockListing('KRX')
    # 검색을 용이하게 하기 위해 "이름 (코드)" 포맷 리스트 생성
    return (df['Name'] + " (" + df['Code'] + ")").tolist()

# ==========================================
# 3. Streamlit UI 구성
# ==========================================
st.set_page_config(page_title="Stock Insights Dashboard", layout="wide")

st.title("📈 주가 정보 분석 대시보드")

# 사이드바 설정
st.sidebar.header("조회 설정")
options = get_stock_list()

# [수정 포인트] selectbox 설정
# index=None을 설정하면 처음 시작 시 비어있으며, 
# 텍스트 입력 시 검색 기능이 활성화되고 'x' 버튼으로 한 번에 지울 수 있습니다.
target_stock = st.sidebar.selectbox(
    "종목 선택", 
    options=options,
    index=None,
    placeholder="종목명 또는 코드를 입력하세요",
)

# 날짜 선택
default_start = datetime.now() - timedelta(days=365)
start_date = st.sidebar.date_input("시작일", default_start)
end_date = st.sidebar.date_input("종료일", datetime.now())

# 종목이 선택되었을 때만 실행
if target_stock:
    ticker_code = target_stock.split("(")[1].replace(")", "")
    
    # 데이터 로드
    df = get_stock_data(ticker_code, start_date, end_date)

    if df is not None and not df.empty:
        # 상단 메트릭 표시
        last_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]
        delta = last_price - prev_price
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("현재가", f"{last_price:,.0f} 원", f"{delta:,.0f} 원")
        col2.metric("고가", f"{df['High'].iloc[-1]:,.0f} 원")
        col3.metric("저가", f"{df['Low'].iloc[-1]:,.0f} 원")
        col4.metric("거래량", f"{df['Volume'].iloc[-1]:,.0f}")

        # 차트 영역
        tab1, tab2 = st.tabs(["캔들스틱 차트", "종가 라인 차트"])
        
        with tab1:
            fig = go.Figure(data=[go.Candlestick(
                x=df.index,
                open=df['Open'],
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                name=target_stock
            )])
            fig.update_layout(template="plotly_white", height=600, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig, use_container_width=True)

        with tab2:
            st.line_chart(df['Close'])

        with st.expander("Raw Data 보기"):
            st.dataframe(df.sort_index(ascending=False), use_container_width=True)
    else:
        st.warning("조회된 데이터가 없습니다. 종목 코드나 날짜를 확인해주세요.")
else:
    st.info("왼쪽 사이드바에서 종목을 선택해 주세요.")

st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Data by FinanceDataReader")
