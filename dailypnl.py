Below we share our complete backtesting code with file paths and IPs redacted (shown as ????). This is a simple system that calculates performance based solely on our 15-minute trading signals, without complex trade management capabilities.

By making this code publicly available, we enable full transparency - you can see exactly how we calculate and display all backtest results on our main dashboard.

import sqlite3

import pandas as pd

import requests

from datetime import datetime, timedelta

from datetime import timezone

import time

import subprocess

DB_PATH = "/????????????????????????.db"

INDEX_BLACKLIST = {

"NDX", "SPX", "DJI", "000001", "GBPUSD", "USDJPY",

"XAUUSD", "EURUSD", "BZ1!", "NI225"

}

def init_pnl_cache_table():

conn = sqlite3.connect(DB_PATH)

cur = conn.cursor()

cur.execute("""

CREATE TABLE IF NOT EXISTS daily_pnl_cache (

symbol TEXT,

day INTEGER,

pnl REAL,

PRIMARY KEY(symbol, day)

)

""")

conn.commit()

conn.close()

def get_pnl_cache(symbol, day):

conn = sqlite3.connect(DB_PATH)

cur = conn.cursor()

cur.execute("SELECT pnl FROM daily_pnl_cache WHERE symbol=? AND day=?", (symbol, day))

row = cur.fetchone()

conn.close()

return row[0] if row else None

def set_pnl_cache(symbol, day, pnl):

conn = sqlite3.connect(DB_PATH)

cur = conn.cursor()

cur.execute("REPLACE INTO daily_pnl_cache (symbol, day, pnl) VALUES (?, ?, ?)", (symbol, day, pnl))

conn.commit()

conn.close()

def normalize_symbol(symbol):

symbol = symbol.replace(".P", "")

special_map = {

"1000BONKUSDT": "BONKUSDT",

"1000FLOKIUSDT": "FLOKIUSDT",

"1000PEPEUSDT": "PEPEUSDT",

"1000SHIBUSDT": "SHIBUSDT"

}

return special_map.get(symbol, symbol)

def round_to_15m(ts):

return ts - (ts % (15 * 60))

def fetch_ohlcv(symbol, start_time, end_time):

MIN_TIME_RANGE = 900

if end_time - start_time < MIN_TIME_RANGE:

end_time = start_time + MIN_TIME_RANGE

url = f"????????????????????:??????????????????????????/ohlcv?symbol={symbol}&interval=15m&start={int(start_time)}&end={int(end_time)}"

time.sleep(0.2)

try:

resp = requests.get(url, timeout=15)

result = resp.json()

if isinstance(result, dict) and "error" in result:

print(f"API Error for {symbol}: {result['error']}")

return []

if not result or not isinstance(result, list):

print(f"Empty OHLCV data for {symbol}")

return []

return result

except Exception as e:

print(f"Failed to fetch OHLCV for {symbol}: {str(e)}")

return []

def calculate_trade_pnl(direction, entry_price, exit_price, qty, portion):

if direction == "buy":

return max((exit_price - entry_price) * qty * portion, 0)

else:

return max((entry_price - exit_price) * qty * portion, 0)

def run_backtest():

conn = sqlite3.connect(DB_PATH)

cur = conn.cursor()

cur.execute("DELETE FROM daily_pnl_cache;")

conn.commit()

conn.close()

print("Cache table cleared.")

eight_days_ago = int((datetime.now(timezone.utc) - timedelta(days=8)).timestamp()

conn = sqlite3.connect(DB_PATH)

signals_df = pd.read_sql_query(

f"""

SELECT * FROM signals

WHERE timeframe='15m' AND timestamp >= {eight_days_ago}

ORDER BY symbol, timestamp ASC

""",

conn,

)

conn.close()

print("UTC now:", datetime.now(timezone.utc))

print("Sample timestamps (UTC):")

print(

signals_df["timestamp"]

.astype(int)

.head()

.apply(lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc))

)

signals_df["date"] = pd.to_datetime(signals_df["timestamp"].astype(int), unit="s", utc=True).dt.date

signals_df["symbol_clean"] = signals_df["symbol"].apply(normalize_symbol)

all_symbols = signals_df["symbol"].unique()

today_utc = datetime.now(timezone.utc).date()

yesterday_utc = today_utc - timedelta(days=1)

days = [yesterday_utc - timedelta(days=i) for i in range(6, -1, -1)]

results = {}

for symbol in all_symbols:

if normalize_symbol(symbol) in INDEX_BLACKLIST:

print(f"Skipping INDEX: {symbol}")

continue

sym_df = signals_df[signals_df["symbol"] == symbol]

sym_clean = normalize_symbol(symbol)

pnl_list = []

for i, day in enumerate(days):

cache_pnl = get_pnl_cache(symbol, day.day)

if cache_pnl is not None and i < 6:

pnl_list.append({"day": day.day, "pnl": round(cache_pnl, 2)})

continue

day_df = sym_df[sym_df["date"] == day]

print(f"Day {day} for {symbol} - signals found: {len(day_df)}")

if day_df.empty:

pnl = 0

else:

pnl = 0

open_pos = None

for idx, row in day_df.iterrows():

entry_time = round_to_15m(int(row["timestamp"]))

entry_price = float(row["price"])

direction = row["signal"].lower()

qty = 25000 / entry_price

if not open_pos:

open_pos = {

"direction": direction,

"entry": entry_price,

"qty": qty,

"open_time": entry_time,

"half_closed": False,

}

continue

end_time = round_to_15m(int(row["timestamp"]))

try:

ohlcv = fetch_ohlcv(sym_clean, open_pos["open_time"], end_time)

time.sleep(0.15)

except Exception as e:

print(f"{sym_clean} OHLCV error: {e}")

ohlcv = []

print(f"OHLCV response [{symbol}]: {len(ohlcv)} bars, time: {open_pos['open_time']} → {end_time}")

if ohlcv:

print("First bar:", ohlcv[0])

else:

print("Empty OHLCV response!")

if not ohlcv or not isinstance(ohlcv[0], list):

print(f"Invalid OHLCV data, symbol: {sym_clean}, day: {day}")

last_price = open_pos["entry"]

pnl_this_trade = calculate_trade_pnl(

open_pos["direction"],

open_pos["entry"],

last_price,

open_pos["qty"],

1.0,

)

pnl += pnl_this_trade

open_pos = {

"direction": direction,

"entry": entry_price,

"qty": qty,

"open_time": entry_time,

"half_closed": False,

}

continue

entry = open_pos["entry"]

direction = open_pos["direction"]

qty = open_pos["qty"]

half_closed = False

pnl_this_trade = 0

tp1 = entry * (1.04 if direction == "buy" else 0.96)

tp2 = entry * (1.06 if direction == "buy" else 0.94)

sl = entry * (0.98 if direction == "buy" else 1.02)

for bar in ohlcv:

try:

high = float(bar[2])

low = float(bar[3])

close = float(bar[4])

except Exception as e:

print(f"Bar parse error: {bar}, e: {e}")

continue

if not half_closed:

if (direction == "buy" and low <= sl) or (direction == "sell" and high >= sl):

pnl_this_trade += calculate_trade_pnl(

direction, entry, sl, qty, 1.0

)

half_closed = False

break

if (direction == "buy" and high >= tp1) or (direction == "sell" and low <= tp1):

pnl_this_trade += calculate_trade_pnl(

direction, entry, tp1, qty, 0.5

)

half_closed = True

if half_closed:

if (direction == "buy" and low <= entry) or (direction == "sell" and high >= entry):

pnl_this_trade += calculate_trade_pnl(

direction, entry, entry, qty, 0.5

)

break

if (direction == "buy" and high >= tp2) or (direction == "sell" and low <= tp2):

pnl_this_trade += calculate_trade_pnl(

direction, entry, tp2, qty, 0.5

)

break

else:

last_price = close if "close" in locals() else entry

pnl_this_trade += calculate_trade_pnl(

direction,

entry,

last_price,

qty,

1.0 if not half_closed else 0.5,

)

pnl += pnl_this_trade

open_pos = {

"direction": row["signal"].lower(),

"entry": entry_price,

"qty": qty,

"open_time": entry_time,

"half_closed": False,

}

if open_pos:

try:

print(f"Closing position OHLCV: {symbol}, {open_pos['open_time']} → {day + timedelta(days=1)}")

ohlcv = fetch_ohlcv(

sym_clean,

open_pos["open_time"],

int(

datetime.combine(

day + timedelta(days=1), datetime.min.time()

).timestamp()

),

)

time.sleep(0.15)

except Exception as e:

ohlcv = []

if ohlcv and isinstance(ohlcv[-1], list):

try:

close = float(ohlcv[-1][4])

except Exception:

close = open_pos["entry"]

else:

print(f"Final OHLCV error: {sym_clean}, {day}")

close = open_pos["entry"]

pnl += calculate_trade_pnl(

open_pos["direction"],

open_pos["entry"],

close,

open_pos["qty"],

1.0,

)

open_pos = None

set_pnl_cache(symbol, day.day, round(pnl, 2))

pnl_list.append({"day": day.day, "pnl": round(pnl, 2)})

results[symbol] = pnl_list

return results

if __name__ == "__main__":

import os

import json

import shutil

if os.path.exists("pnl_results.json"):

os.remove("pnl_results.json")

print("Old pnl_results.json removed.")

init_pnl_cache_table()

res = run_backtest()

with open("pnl_results.json", "w") as f:

json.dump(res, f, indent=2)

print("New pnl_results.json created.")

shutil.copyfile("pnl_results.json", "/????????????????????????????/pnl_results.json")

print("pnl_results.json copied to public folder.")

try:

subprocess.run(["npm", "run", "build"], cwd="/???????????????????????", check=True)

print("Frontend build successful.")

subprocess.run(["cp", "-r", "build/.", "/??????????????????/"], cwd="/p????????????????", check=True)

print("Build files copied to web server directory.")

except subprocess.CalledProcessError as e:

print(f"Frontend build error: {e}")

with open("pnl_results.json", "r") as f:

data_now = f.read()

with open("/??????????????????????/pnl_results.json", "r") as f:

data_public = f.read()

if data_now != data_public:

print("WARNING: JSON output mismatch!")

else:

print("JSON output matches. Calculation is consistent.")