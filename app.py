from datetime import datetime
import os
import sqlite3
import pandas as pd
import streamlit as st

# 網頁基本設定
st.set_page_config(
    page_title="✈️ 機票價格矩陣與歷史走勢儀表板", page_icon="📈", layout="wide"
)

DB_FILE = "flight_smart_monitor.db"


@st.cache_data(ttl=30)
def load_price_logs():
  """載入歷史價格日誌"""
  if not os.path.exists(DB_FILE):
    return pd.DataFrame()
  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql_query(
      "SELECT * FROM price_logs ORDER BY recorded_at ASC", conn
  )
  conn.close()
  return df


@st.cache_data(ttl=30)
def load_matrix_status():
  """載入當前矩陣狀態"""
  if not os.path.exists(DB_FILE):
    return pd.DataFrame()
  conn = sqlite3.connect(DB_FILE)
  df = pd.read_sql_query("SELECT * FROM flight_matrix_history", conn)
  conn.close()
  return df


# 儀表板標題
st.title("✈️ 德國 ➔ 中國/香港 智慧機票矩陣儀表板")
st.markdown("追蹤多出發樞紐與目的地的即時價格、矩陣最低點與歷史走勢波動。")

df_logs = load_price_logs()
df_status = load_matrix_status()

if df_status.empty:
  st.warning(
      "⚠️ 尚未偵測到資料庫檔案或無監控數據。請先執行一次背景爬蟲腳本生成數據！"
  )
else:
  # 側邊欄篩選器
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

  # 頂部核心指標 KPI
  col1, col2, col3 = st.columns(3)
  with col1:
    st.metric(label="監控中的航線組合", value=len(df_status))
  with col2:
    if not filtered_status.empty:
      min_row = filtered_status.loc[filtered_status["lowest_price"].idxmin()]
      st.metric(
          label="目前矩陣全場最低價",
          value=f"{min_row['lowest_price']}",
          delta=f"{min_row['origin']} ➔ {min_row['destination']}",
      )
  with col3:
    st.metric(label="儀表板更新時間", value=datetime.now().strftime("%Y-%m-%d"))

  st.markdown("---")

  # 區域一：歷史價格折線圖
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

  # 區域二：矩陣當前最低價清單表格
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
