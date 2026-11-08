from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import os
import re
import sqlite3
import subprocess
import sys

# 🛡️ 強制將 Playwright 路徑指向統一且可寫入的家目錄
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.expanduser(
    "~/.cache/ms-playwright"
)

# 🛡️ 強制在每次啟動時自動確保 Playwright Chromium 瀏覽器核心就緒
print("🔄 正在檢查並確保 Playwright Chromium 瀏覽器核心已就緒...")
try:
  subprocess.run(
      [sys.executable, "-m", "playwright", "install", "chromium"],
      check=True,
      capture_output=True,
  )
  print("✅ Playwright 瀏覽器核心檢查/安裝完成！")
except Exception as e:
  print(f"⚠️ 安裝提示或略過: {e}")

from playwright.sync_api import sync_playwright

DB_FILE = "flight_smart_monitor.db"

# ==================== 🧠 聰明矩陣設定區 ====================
# 1. 出發地清單（杜塞爾多夫及德國周邊樞紐）
ORIGIN_HUBS = ["DUS", "CGN", "FRA", "AMS"]

# 2. 目的地清單（香港與中國主要樞紐）
DESTINATION_HUBS = ["HKG", "CAN", "SZX", "PVG", "PEK"]

# 3. 預算上限與目標出發日期
GLOBAL_TARGET_PRICE = 800
TARGET_DATE = "2026-12-15"
# ========================================================


def init_db():
  """初始化 SQLite 資料庫，建立狀態表與歷史日誌表"""
  conn = sqlite3.connect(DB_FILE)
  cursor = conn.cursor()

  # 1. 矩陣狀態表（記錄歷史最低價與更新時間）
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

  # 2. 歷史日誌表（專門用來給 Streamlit 繪製折線圖）
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
  """每次爬蟲檢查時，無條件寫入一筆歷史價格日誌"""
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
  print(f"📝 [日誌] 已記錄: {origin} ➔ {destination} = {price} €")


def update_matrix_status(origin, destination, flight_date, current_price):
  """更新矩陣最低價狀態表"""
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
  """升級版：使用雙策略（DOM 精準尋找 + 頁面廣域正則）穩定抓取 Google Flights 價格"""
  with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="de-DE",  # 歐洲地區德語系格式
    )
    page = context.new_page()
    url = f"https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{destination}%20on%20{date}"

    try:
      page.goto(url, timeout=40000)
      page.wait_for_timeout(8000)  # 給予足夠時間讓 JavaScript 渲染價格矩陣

      prices = []

      # 策略 A：尋找網頁中包含歐元或貨幣符號的元素
      elements = page.locator('div[role="region"], div[jscontroller], span').all()
      for el in elements:
        try:
          text = el.inner_text().strip()
          if len(text) < 30 and ("€" in text or "EUR" in text):
            match = re.search(r"([\d.,]+)\s*(?:€|EUR)", text)
            if match:
              raw_num = match.group(1)
              clean_num = raw_num.replace(".", "").replace(",", "")
              val = int(clean_num)
              if 150 <= val <= 8000:
                prices.append(val)
        except:
          continue

      # 策略 B：若策略 A 未命中，全面退回廣域正則掃描頁面內文
      if not prices:
        body_text = page.inner_text("body")
        all_matches = re.findall(
            r"(?:€|EUR)\s*([\d.,]+)|([\d.,]+)\s*(?:€|EUR)", body_text
        )
        for m in all_matches:
          num_str = m[0] if m[0] else m[1]
          if num_str:
            clean_num = num_str.replace(".", "").replace(",", "")
            try:
              val = int(clean_num)
              if 150 <= val <= 8000:
                prices.append(val)
            except:
              continue

      browser.close()
      if prices:
        return min(prices)
      return None

    except Exception as e:
      print(f"❌ 爬取 {origin} -> {destination} 失敗: {e}")
      browser.close()
      return None


def scan_single_route(args):
  origin, destination, target_date = args
  print(f"正在平行掃描航線: {origin} ➔ {destination} ({target_date})")
  price = get_google_flight_price(origin, destination, target_date)
  return origin, destination, target_date, price


if __name__ == "__main__":
  init_db()
  tasks = [
      (origin, dest, TARGET_DATE)
      for origin in ORIGIN_HUBS
      for dest in DESTINATION_HUBS
  ]
  print(
      f"🚀 開始執行多執行緒矩陣掃描：總計 {len(tasks)} 條航線同步發動中..."
  )

  # 使用最多 3 個執行緒平行抓取
  with ThreadPoolExecutor(max_workers=3) as executor:
    futures = [executor.submit(scan_single_route, task) for task in tasks]
    for future in as_completed(futures):
      origin, destination, flight_date, current_price = future.result()
      if current_price:
        log_price_to_db(origin, destination, flight_date, current_price)
        update_matrix_status(origin, destination, flight_date, current_price)
      else:
        print(f"⚠️ 無法取得 {origin} ➔ {destination} 價格。")
