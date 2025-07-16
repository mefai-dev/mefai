
import sqlite3

import pandas as pd

import requests

from datetime import datetime, timedelta, timezone

import time

import json

import os

import shutil

import subprocess

from multiprocessing import Pool, cpu_count

# --- Configuration Loading ---

# All sensitive paths and URLs are now loaded from an external config file.

# This makes the script secure for public sharing.

try:

with open('config.json', 'r') as f:

config = json.load(f)

DB_PATH = config['db_path']

OHLCV_API_URL = config['ohlcv_api_url']

FRONTEND_PUBLIC_PATH = config['frontend_public_path']

except FileNotFoundError:

print("❌ CRITICAL ERROR: config.json not found. Please create it before running.")

exit()

except KeyError as e:

print(f"❌ CRITICAL ERROR: Missing key in config.json: {e}")

exit()

INDEX_BLACKLIST = {

"NDX", "SPX", "DJI", "000001", "GBPUSD", "USDJPY",

"XAUUSD", "EURUSD", "BZ1!", "NI225"

}

# Standard TP/SL rules for all symbols

ASSET_CONFIG = {

"default": {

"tp1_ratio": 1.02,

"tp2_ratio": 1.03,

"sl_ratio": 0.99

}

}

def clear_pnl_cache():

"""Clears the old PnL results from the database cache."""

try:

conn = sqlite3.connect(DB_PATH)

cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS daily_pnl_cache (symbol TEXT, day INTEGER, pnl REAL, PRIMARY KEY(symbol, day))")

cur.execute("DELETE FROM daily_pnl_cache;")

conn.commit()

conn.close()

print(f"🧹 PnL Cache table cleared successfully.")

except Exception as e:

print(f"❌ Could not clear PnL cache: {e}")

def filter_by_candle_close(df, timeframe):

"""Filters signals by taking only the last signal of each candle period."""

if df.empty: return df

df['timestamp_dt'] = pd.to_datetime(df['timestamp'].astype(float), unit='s', utc=True)

freq_map = {'1h': 'h', '15m': '15min', '30m': '30min', '4h': '4h', '1d': 'D', '5m': '5min', '1m': '1min'}

freq = freq_map.get(timeframe, 'h')

df['candle_start'] = df['timestamp_dt'].dt.floor(freq)

stable_signals_df = df.groupby('candle_start').last().reset_index()

return stable_signals_df.drop(columns=['timestamp_dt', 'candle_start'])

def normalize_symbol(symbol):

"""Normalizes symbol names, e.g., 1000PEPEUSDT -> PEPEUSDT."""

symbol = symbol.replace(".P", "")

special_map = {"1000BONKUSDT": "BONKUSDT", "1000FLOKIUSDT": "FLOKIUSDT", "1000PEPEUSDT": "PEPEUSDT", "1000SHIBUSDT": "SHIBUSDT"}

return special_map.get(symbol, symbol)

def fetch_ohlcv_data(symbol, start_ts, end_ts):

"""Fetches OHLCV data using the URL from the config file."""

url = f"{OHLCV_API_URL}?symbol={symbol}&interval=1m&start={int(start_ts)}&end={int(end_ts)}"

try:

resp = requests.get(url, timeout=60)

data = resp.json()

if not data or not isinstance(data, list) or (isinstance(data, dict) and "error" in data): return None

df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

for col in df.columns: df[col] = pd.to_numeric(df[col])

return df

except Exception as e:

print(f"Error fetching OHLCV for {symbol}: {e}")

return None

def calculate_trade_pnl(direction, entry_price, exit_price, qty, portion):

"""Calculates the Profit or Loss for a trade."""

return ((exit_price - entry_price) if direction == "buy" else (entry_price - exit_price)) * qty * portion

def process_symbol(args):

"""The main backtesting logic for a single symbol."""

symbol, timeframe, signals_df, eight_days_ago_ts = args

sym_clean = normalize_symbol(symbol)

print(f"🚀 Processing {symbol} for {timeframe} timeframe...")

ohlcv_df = fetch_ohlcv_data(sym_clean, eight_days_ago_ts, int(time.time()))

if ohlcv_df is None:

print(f"Could not fetch OHLCV data for {symbol}. Skipping.")

return symbol, []

sym_signals = signals_df[signals_df['symbol'] == symbol].copy()

sym_signals = filter_by_candle_close(sym_signals, timeframe)

if sym_signals.empty: return symbol, []

sym_signals["date"] = pd.to_datetime(sym_signals["timestamp"].astype(float), unit='s', utc=True).dt.date

config_rules = ASSET_CONFIG["default"]

price_multiplier = 1000.0 if "1000" in symbol and symbol.startswith("1000") else 1.0

open_pos = None

daily_pnl_map = {}

for idx, row in sym_signals.iterrows():

entry_time = int(row["timestamp"])

entry_price = float(row["price"])

direction = row["signal"].lower()

if not open_pos:

open_pos = {"direction": direction, "entry": entry_price, "qty": 25000 / entry_price, "open_time": entry_time}

continue

if direction == open_pos["direction"]: continue

end_time = entry_time

trade_ohlcv_df = ohlcv_df[(ohlcv_df['timestamp'] >= open_pos["open_time"]) & (ohlcv_df['timestamp'] < end_time)]

pnl_this_trade = 0

if trade_ohlcv_df.empty:

pnl_this_trade = calculate_trade_pnl(open_pos["direction"], open_pos["entry"], entry_price, open_pos["qty"], 1.0)

else:

entry, pos_direction, pos_qty = open_pos["entry"], open_pos["direction"], open_pos["qty"]

half_closed = False

if pos_direction == "buy": tp1, tp2, sl = entry * config_rules["tp1_ratio"], entry * config_rules["tp2_ratio"], entry * config_rules["sl_ratio"]

else: tp1, tp2, sl = entry * (2 - config_rules["tp1_ratio"]), entry * (2 - config_rules["tp2_ratio"]), entry * (2 - config_rules["sl_ratio"])

trade_closed_by_logic = False

for bar_ts, o, h, l, c, v in trade_ohlcv_df.values:

high, low = h * price_multiplier, l * price_multiplier

if not half_closed:

if (pos_direction == "buy" and low <= sl) or (pos_direction == "sell" and high >= sl):

pnl_this_trade += calculate_trade_pnl(pos_direction, entry, sl, pos_qty, 1.0); trade_closed_by_logic = True; break

if (pos_direction == "buy" and high >= tp1) or (pos_direction == "sell" and low <= tp1):

pnl_this_trade += calculate_trade_pnl(pos_direction, entry, tp1, pos_qty, 0.5); half_closed = True

if half_closed:

if (pos_direction == "buy" and low <= entry) or (pos_direction == "sell" and high >= entry):

pnl_this_trade += calculate_trade_pnl(pos_direction, entry, entry, pos_qty, 0.5); trade_closed_by_logic = True; break

if (pos_direction == "buy" and high >= tp2) or (pos_direction == "sell" and low <= tp2):

pnl_this_trade += calculate_trade_pnl(pos_direction, entry, tp2, pos_qty, 0.5); trade_closed_by_logic = True; break

if not trade_closed_by_logic:

final_close = trade_ohlcv_df['close'].iloc[-1] * price_multiplier

remaining_portion = 0.5 if half_closed else 1.0

pnl_this_trade += calculate_trade_pnl(pos_direction, entry, final_close, pos_qty, remaining_portion)

trade_date = datetime.fromtimestamp(open_pos["open_time"], tz=timezone.utc).date()

daily_pnl_map[trade_date] = daily_pnl_map.get(trade_date, 0) + pnl_this_trade

open_pos = {"direction": direction, "entry": entry_price, "qty": 25000 / entry_price, "open_time": entry_time}

pnl_list = []

days_range = [(datetime.now(timezone.utc).date() - timedelta(days=i)) for i in range(7, 0, -1)]

for day_date in days_range:

pnl = daily_pnl_map.get(day_date, 0)

pnl_list.append({"day": day_date.day, "pnl": round(pnl, 2)})

print(f"✅ Finished processing for {symbol} on {timeframe}.")

return symbol, pnl_list

if __name__ == "__main__":

overall_start_time = time.time()

TIMEFRAMES_TO_RUN = ['1m', '5m', '15m', '30m', '1h']

for timeframe in TIMEFRAMES_TO_RUN:

print(f"\n{'='*20} STARTING BACKTEST FOR TIMEFRAME: {timeframe} {'='*20}")

start_time_tf = time.time()

clear_pnl_cache()

conn = sqlite3.connect(DB_PATH)

eight_days_ago_ts = int((datetime.now(timezone.utc) - timedelta(days=8)).timestamp())

signals_df = pd.read_sql_query(f"SELECT * FROM signals WHERE timeframe='{timeframe}' AND timestamp >= {eight_days_ago_ts}", conn)

conn.close()

if signals_df.empty:

print(f"No signals found for timeframe {timeframe}. Skipping.")

continue

all_symbols = [s for s in signals_df["symbol"].unique() if normalize_symbol(s) not in INDEX_BLACKLIST]

tasks = [(symbol, timeframe, signals_df, eight_days_ago_ts) for symbol in all_symbols]

num_processes = max(1, cpu_count() - 1)

print(f"Starting parallel processing with {num_processes} cores for {len(all_symbols)} symbols...")

with Pool(processes=num_processes) as pool:

results_list = pool.map(process_symbol, tasks)

final_results = {symbol: pnl_data for symbol, pnl_data in results_list if pnl_data}

output_filename = f"pnl_results_{timeframe}.json"

with open(output_filename, "w") as f:

json.dump(final_results, f, indent=2)

print(f"✅ New results file created: {output_filename}")

try:

public_path = os.path.join(FRONTEND_PUBLIC_PATH, output_filename)

shutil.copyfile(output_filename, public_path)

print(f"📁 {output_filename} copied to public folder.")

except Exception as e:

print(f"❌ File copy or build error: {e}")

end_time_tf = time.time()

print(f"--- Execution time for {timeframe}: {end_time_tf - start_time_tf:.2f} seconds ---")

overall_end_time = time.time()

print(f"\n{'='*20} ALL BACKTESTS COMPLETED {'='*20}")

print(f"--- Total execution time for all timeframes: {overall_end_time - overall_start_time:.2f} seconds ---")

