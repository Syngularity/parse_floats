import requests
import yfinance as yf
import re
import os
import concurrent.futures
import time
from datetime import datetime
import influxdb_client
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import logging
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

nyse_url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_tickers.json"
nasdaq_url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.json"

nyse_response = requests.get(nyse_url)
nasdaq_response = requests.get(nasdaq_url)
nyse_tickers_data = nyse_response.json()
nasdaq_tickers_data = nasdaq_response.json()
tickers = [ticker.strip() for ticker in nyse_tickers_data + nasdaq_tickers_data]
valid_ticker_pattern = re.compile(r'^[A-Za-z0-9._-]+$')

current_date = datetime.now().strftime('%Y-%m-%d')
current_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# InfluxDB setup
org = os.getenv("INFLUXDB_ORG")
url = os.getenv("INFLUXDB_URL")
token = os.getenv("INFLUXDB_TOKEN")
bucket = os.getenv("INFLUXDB_BUCKET")


client = influxdb_client.InfluxDBClient(url=url, token=token, org=org)
write_api = client.write_api(write_options=SYNCHRONOUS)

def fetch_float_shares(ticker):
    sanitized_ticker = ticker.replace(" ", "")
    if valid_ticker_pattern.match(sanitized_ticker):
        try:
            stock = yf.Ticker(sanitized_ticker)
            stock_info = stock.info
            
            if 'floatShares' in stock_info:
                float_shares = stock_info['floatShares']
                point = Point("float") \
                    .tag("ticker", sanitized_ticker) \
                    .field("shares", float_shares) \
                    .time(current_date)
                write_api.write(bucket=bucket, org=org, record=point)

            else:
                point = Point("float_failure") \
                    .tag("ticker", sanitized_ticker) \
                    .field("reason", "Float shares data not found") \
                    .time(current_date)
                write_api.write(bucket=bucket, org=org, record=point)
        except requests.exceptions.HTTPError as e:
            reason = 'Client 404 error' if e.response.status_code == 404 else str(e)
            point = Point("fetch_failure") \
                .tag("ticker", sanitized_ticker) \
                .field("reason", reason) \
                .time(current_date)
            write_api.write(bucket=bucket, org=org, record=point)
        except json.decoder.JSONDecodeError as e:
            point = Point("fetch_failure") \
                .tag("ticker", sanitized_ticker) \
                .field("reason", str(e)) \
                .time(current_date)
            write_api.write(bucket=bucket, org=org, record=point)
        except Exception as e:
            point = Point("fetch_failure") \
                .tag("ticker", sanitized_ticker) \
                .field("reason", str(e)) \
                .time(current_date)
            write_api.write(bucket=bucket, org=org, record=point)
    else:
        logging.debug(f"Invalid ticker symbol found and skipped: {sanitized_ticker}")

logging.info(f"Float Processing Started")
start_time = time.time()

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(fetch_float_shares, ticker): ticker for ticker in tickers}
    for future in concurrent.futures.as_completed(futures):
        try:
            future.result() 
        except Exception as e:
            logging.warning(f"Error processing ticker: {e}")

# Calculate total runtime
end_time = time.time()
runtime = end_time - start_time

# Log summary to InfluxDB
summary_point = Point("float_add_result") \
    .field("num_floats_added", len(tickers)) \
    .field("runtime", runtime) \
    .time(current_datetime)
write_api.write(bucket=bucket, org=org, record=point)

client.close()
logging.info(f"Float Processing Completed in {runtime}")
