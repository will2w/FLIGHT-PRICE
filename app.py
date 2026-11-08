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
  log_output = "🚀 開始執行多執行緒平行爬蟲...\n"
  log_box = st.empty()
  log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)

  try:
    process = subprocess.Popen(
        [sys.executable, "flight_radar_smart.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in iter(process.stdout.readline, ""):
      if line:
        log_output += line
        log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)

    process.stdout.close()
    process.wait()

    if process.returncode == 0:
      log_output += "\n✅ 矩陣掃描完畢，資料庫已更新！"
      log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)
      return True
    else:
      log_output += f"\n❌ 執行結束，返回碼: {process.returncode}"
      log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)
      return False
  except Exception as e:
    log_output += f"\n❌ 發生例外錯誤: {str(e)}"
    log_box.text_area("執行日誌 (Live Logs)", value=log_output, height=250)
    return False


def ensure_db_exists():
  if not os.path.exists(DB_FILE) or os.path.getsize(DB_FILE) == 0:
    st.warning("⚠️ 尚未偵測到資料庫。正在自動執行第一次平行掃描...")
    success = run_scraper_with_live_logs()
    if success:
      st.success("✅ 資料庫初始化成功！")
      st.rerun()


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
  except:
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
  except:
    return pd.DataFrame()


# 側邊欄控制台
st.sidebar.header("📱 雲端行動控制台")
if st.sidebar.button("🔄 立即手動平行抓取最新機票"):
  with st.spinner("正在以多執行緒掃描矩陣..."):
    success = run_scraper_with_live_logs()
    if success:
      st.sidebar.success("✅ 更新成功！")
      st.cache_data.clear()
      st.rerun()

st.title("✈️ 德國 ➔ 中國/香港 智慧機票矩陣儀表板")
st.markdown("追蹤多出發樞紐與目的地的即時價格、歷史均價與破盤特價警示。")

df_logs = load_price_logs()
df_status = load_matrix_status()

if df_status.empty:
  st.warning(
      "⚠️ 目前資料庫仍無數據。請點擊左側側邊欄的 **「🔄 立即手動平行抓取最新機票」**"
      " 按鈕！"
  )
else:
  # 計算歷史平均價格作為基準
  if not df_logs.empty:
    avg_price = df_logs["price"].mean()
  else:
    avg_price = 800  # 預設基準

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

  # 🚨 檢查是否有低於歷史均價的特價機票
  cheap_deals = filtered_status[filtered_status["lowest_price"] < avg_price]

  if not cheap_deals.empty:
    st.error(
        f"🚨 **發現特價機票情報！** 目前有 {len(cheap_deals)}"
        f" 條航線價格低於歷史均價 ({int(avg_price)} €)，快把握機會下手！"
    )

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
    st.metric(
        label="歷史平均基準價",
        value=f"{int(avg_price)} €",
        delta="特價分界線",
    )

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
