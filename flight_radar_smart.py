from datetime import datetime
import os
import re
import sqlite3
from playwright.sync_api import sync_playwright

DB_FILE = "flight_smart_monitor.db"

# ==================== 🧠 聰明矩陣設定區 ====================
# 1. 出發地清單（杜塞爾多夫及德國周邊樞紐）
ORIGIN_HUBS = ["DUS", "CGN", "FRA", "AMS"]

# 2. 目的地清單（香港與中國主要樞紐）
DESTINATION_HUBS = ["HKG", "CAN", "SZX", "PVG", "PEK"]

# 3. 預算上限 (歐元或對應幣別數值)
GLOBAL_TARGET_PRICE = 800
TARGET_DATE = "2026-12-15"  # 預計出發日期
# ========================================================


def init_db():
  """初始化 SQLite 資料庫，建立狀態表與歷史日誌表"""
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS flight_matrix_history (
            route_key TEXT PRIMARY KEY,
            origin TEXT,
            destination TEXT,
            flight_date TEXT,
            lowest_price INTEGER,
            last_notified_price INTEGER,
            updated_time TEXT
        )
    """)

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_key TEXT,
            origin TEXT,
            destination TEXT,
            flight_date TEXT,
            price INTEGER,
            recorded_at TEXT
        )
    """)

  conn.commit()
  conn.close()


def log_price_to_db(origin, destination, flight_date, price):
  """每次爬蟲檢查時，強制寫入一筆歷史價格日誌"""
  if price is None:
    return

  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  route_key = f"{origin}-{destination}-{flight_date}"
  recorded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  cursor.execute(
      """
        INSERT INTO price_logs (route_key, origin, destination, flight_date, price, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
      (route_key, origin, destination, flight_date, price, recorded_at),
  )

  conn.commit()
  conn.close()
  print(f" 📝 [日誌] 已記錄: {origin} ➔ {destination} = {price}")


def update_matrix_status(origin, destination, flight_date, current_price):
  """更新矩陣最低價狀態"""
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()
  route_key = f"{origin}-{destination}-{flight_date}"
  now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  cursor.execute(
      "SELECT lowest_price FROM flight_matrix_history WHERE route_key = ?",
      (route_key,),
  )
  row = cursor.fetchone()

  if row is None:
    cursor.execute(
        """
            INSERT INTO flight_matrix_history (route_key, origin, destination, flight_date, lowest_price, last_notified_price, updated_time)
            VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (
            route_key,
            origin,
            destination,
            flight_date,
            current_price,
            now_str,
        ),
    )
  else:
    historical_low = row[0]
    if current_price < historical_low:
      cursor.execute(
          """
                UPDATE flight_matrix_history 
                SET lowest_price = ?, updated_time = ? 
                WHERE route_key = ?
            """,
          (current_price, now_str, route_key),
      )

  conn.commit()
  conn.close()


def get_google_flight_price(origin, destination, date):
  """利用 Playwright 掃描 Google Flights 矩陣價格"""
  with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="de-DE",
    )
    page = context.new_page()
    url = f"https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{destination}%20on%20{date}"

    try:
      page.goto(url, timeout=40000)
      page.wait_for_timeout(6000)

      price_locators = page.locator("div, span").filter(
          has_text=re.compile(r"€|EUR|TWD|NT\$|\$")
      )
      prices = []
      count = price_locators.count()
      for i in range(min(count, 30)):
        text = price_locators.nth(i).inner_text().strip()
        match = re.search(r"(?:€|EUR|TWD|NT\$|\$)\s*([\d,.]+)", text)
        if match:
          clean_str = match.group(1).replace(",", "").replace(".", "")
          try:
            val = int(clean_str)
            if 100 <= val <= 10000:
              prices.append(val)
          except:
            continue

      browser.close()
      if prices:
        return min(prices)
      return None
    except Exception as e:
      print(f"爬取 {origin} -> {destination} 失敗: {e}")
      browser.close()
      return None


if __name__ == "__main__":
  init_db()
  print(
      f"🚀 開始執行矩陣掃描：{len(ORIGIN_HUBS)} 個出發地 x"
      f" {len(DESTINATION_HUBS)} 個目的地"
  )

  for origin in ORIGIN_HUBS:
    for destination in DESTINATION_HUBS:
      print(f"\n正在掃描航線: {origin} ➔ {destination} ({TARGET_DATE})")
      current_price = get_google_flight_price(
          origin, destination, TARGET_DATE
      )

      if current_price:
        log_price_to_db(origin, destination, TARGET_DATE, current_price)
        update_matrix_status(origin, destination, TARGET_DATE, current_price)
      else:
        print(f" ⚠️ 無法取得 {origin} ➔ {destination} 價格。")
