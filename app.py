from datetime import datetime
import os
import sqlite3
import subprocess
import sys
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="✈️ 德國-中國機票矩陣與歷史走勢", page_icon="📈", layout="wide"
)

DB_FILE = "flight_smart_monitor.db"


def run_scraper_with_live_logs():
  """執行爬蟲並將標準輸出（Stdout）即時串流到 Streamlit 的文字框中"""
  log_output = "🚀 開始執行爬蟲與矩陣掃描...\n"
  log_box = st.empty()  # 建立一個動態容器來刷新文字框
  log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)

  try:
    # 使用 Popen 即時捕捉執行過程中的每一行輸出
    process = subprocess.Popen(
        [sys.executable, "flight_radar_smart.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # 逐行讀取輸出並即時更新畫面的 text_area
    for line in iter(process.stdout.readline, ""):
      if line:
        log_output += line
        log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)

    process.stdout.close()
    process.wait()

    if process.returncode == 0:
      log_output += "\n✅ 爬蟲執行完畢，資料庫已更新！"
      log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)
      return True
    else:
      log_output += f"\n❌ 爬蟲執行結束，返回碼: {process.returncode}"
      log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)
      return False

  except Exception as e:
    log_output += f"\n❌ 發生例外錯誤: {str(e)}"
    log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)
    return False


def ensure_db_exists():
  """🛡️ 自動防護：若無資料庫，自動執行即時日誌爬蟲生成"""
  if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
    st.warning(
        "⚠️ 尚未偵測到有效的資料庫檔案。系統正在背景自動執行第一次爬蟲，請觀看下方即時日誌..."
    )
    success = run_scraper_with_live_logs()
    if success:
      st.success("✅ 初始資料庫生成成功！正在載入儀表板...")
      st.rerun()


# 啟動時檢查
ensure_db_exists()


@st.cache_data(ttl=10)
def load_price_logs():
  if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
    return pd.DataFrame()
  try:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        "SELECT * FROM price_logs ORDER BY recorded_at ASC", conn
    )
    conn.close()
    return df
  except Exception:
    return pd.DataFrame()


@st.cache_data(ttl=10)
def load_matrix_status():
  if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
    return pd.DataFrame()
  try:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM flight_matrix_history", conn)
    conn.close()
    return df
  except Exception:
    return pd.DataFrame()


# 側邊欄控制台
st.sidebar.header("📱 雲端行動控制台")
if st.sidebar.button("🔄 立即手動抓取最新機票"):
  with st.spinner("正在執行即時矩陣掃描..."):
    success = run_scraper_with_live_logs()
    if success:
      st.sidebar.success("✅ 抓取成功！")
      st.cache_data.clear()
      st.rerun()

st.title("✈️ 德國 ➔ 中國/香港 智慧機票矩陣儀表板")
st.markdown("追蹤多出發樞紐與目的地的即時價格、矩陣最低點與歷史走勢波動。")

df_logs = load_price_logs()
df_status = load_matrix_status()

if df_status.empty:
  st.warning(
      "⚠️ 目前資料庫仍無數據。請點擊左側側邊欄的 **「🔄 立即手動抓取最新機票」**"
      " 按鈕來觸發即時掃描！"
  )
else:
  st.sidebar.markdown("---")
  st.sidebar.header("🔍 篩選與檢視條件")
  df_status["route_display"] = (
      df_status["origin"] + " ➔ " + df_status["destination"]
  )
  selected_routes = st.sidebar.multiselect(
      "選擇航線",
      options=df_status["route_display"].unique(),
      default=df_status["route_display"].unique(),
  )

  filtered_status = df_status[df_status["route_display"].isin(selected_routes)]

  col1, col2, col3 = st.columns(3)
  with col1:
    st.metric(label="監控中的航線組合", value=len(df_status))
  with col2:
    if not filtered_status.empty:
      min_row = filtered_status.loc[filtered_status["lowest_price"].idxmin()]
      st.metric(
          label="目前矩陣全場最低價",
          value=f"{min_row['lowest_price']} €",
          delta=f"{min_row['origin']} ➔ {min_row['destination']}",
      )
  with col3:
    st.metric(label="儀表板更新時間", value=datetime.now().strftime("%Y-%m-%d"))

  st.markdown("---")

  st.subheader("📉 航線歷史價格波動走勢 (Price Trend)")
  if not df_logs.empty:
    df_logs["route_display"] = (
        df_logs["origin"] + " ➔ " + df_logs["destination"]
    )
    filtered_logs = df_logs[df_logs["route_display"].isin(selected_routes)]

    if not filtered_logs.empty:
      chart_pivot = filtered_logs.pivot_table(
          index="recorded_at",
          columns=["route_display", "flight_date"],
          values="price",
      )
      st.line_chart(chart_pivot, use_container_width=True)
    else:
      st.info("尚無符合篩選條件的歷史日誌記錄。")
  else:
    st.info("尚無歷史價格記錄。")

  st.markdown("---")

  st.subheader("📋 矩陣航線最新狀態總覽")
  st.dataframe(
      filtered_status[
          [
              "origin",
              "destination",
              "flight_date",
              "lowest_price",
              "updated_time",
          ]
      ],
      use_container_width=True,
  )
