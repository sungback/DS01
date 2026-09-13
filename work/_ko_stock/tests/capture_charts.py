"""
app.py 의 차트 그리기 블록을 그대로 실행해 PNG 를 남긴다.
수정 전/후 바이트 비교용.
"""
import io, sys, warnings
from pathlib import Path
from threading import RLock
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D
import mplfinance as mpf

from conftest_paths import APP, DATA_FOLDER, LIST_FILE, BUNDLE_FILE, PROJECT, SCRATCH

warnings.filterwarnings("ignore")

P = Pathstr(PROJECT)
APP_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else APP
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else (SCRATCH / "charts")
OUT.mkdir(parents=True, exist_ok=True)
MODE = sys.argv[3] if len(sys.argv) > 3 else "new"

fm.fontManager.addfont(str(P / "fonts" / "NanumGothic.ttf"))
font = "AppleGothic"
plt.rcParams["font.family"] = font
plt.rcParams["axes.unicode_minus"] = False

mc = mpf.make_marketcolors(up="red", down="#4A90E2", inherit=True)
style = mpf.make_mpf_style(base_mpf_style="yahoo", marketcolors=mc,
                           mavcolors=["orange", "green", "purple", "black"],
                           rc={"font.family": font})
ma_legend = [Line2D([0], [0], color=c, lw=2, label=f"MA{p}")
             for p, c in zip((20, 60, 120, 200),
                             ("orange", "green", "purple", "black"))]

CODES = ["005930", "000660", "005380"]
CHART_DAYS = 60
src = APP_FILE.read_text()

class StStub:
    def warning(self, *a, **k): pass
    def pyplot(self, fig, **k):
        buf = io.BytesIO(); fig.savefig(buf, format="png")
        self.last = buf.getvalue()
    def image(self, data, **k): self.last = data

for code in CODES:
    row = {"매수가": float("nan"), "손절가": float("nan"),
           "1R(30%매도)": float("nan"), "2R(30%매도)": float("nan")}
    title = f"테스트 | 균형형 | 위험도 낮음\n추세와 과열 정도의 균형이 좋은 종목"
    st = StStub()

    if MODE == "old":
        chart_df = pd.read_csv(P / "stock_data" / f"{code}.csv",
                               index_col="Date", parse_dates=["Date"]).sort_index()
        block = src[src.index("    plot_df = chart_df.copy()"):
                    src.index("        plt.close(fig)") + len("        plt.close(fig)")]
        block = "\n".join(l[4:] if l.startswith("    ") else l
                          for l in block.splitlines())
        ns = {"chart_df": chart_df, "CHART_DAYS": CHART_DAYS, "PLOT_LOCK": RLock(),
              "mpf": mpf, "plt": plt, "style": style, "row": row, "title": title,
              "Line2D": Line2D, "ma_legend": ma_legend, "st": st, "pd": pd}
        exec(compile(block, str(APP_FILE), "exec"), ns)
        png = st.last
    else:
        import ast, logging
        tree = ast.parse(src)
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "render_chart"]
        assert fn, "render_chart 함수를 찾지 못했습니다"
        fn[0].decorator_list = []
        ns = {"pd": pd, "mpf": mpf, "plt": plt, "style": style, "io": io,
              "Line2D": Line2D, "ma_legend": ma_legend, "PLOT_LOCK": RLock(),
              "DATA_FOLDER": P / "stock_data", "logger": logging.getLogger("x")}
        exec(compile(ast.Module(body=fn, type_ignores=[]), "app.py", "exec"), ns)
        png, _ = ns["render_chart"](code, CHART_DAYS, title, None, None, None, None, "v")

    (OUT / f"{code}.png").write_bytes(png)
    print(f"  {code}.png  {len(png):,} bytes")
