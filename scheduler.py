import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
import logging
import threading
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

API_SCHEDULE_URL = "http://localhost:8765/api/schedule"
API_CRAWL_ROW_URL = "http://localhost:8765/api/crawl-row"

last_triggered = {}

def calculate_next_time(last_fetched_str, freq):
    if not freq or freq == "手动不自动":
        return None
        
    try:
        # Check if it's an ISO date
        if "T" in freq and freq.count("-") >= 2 and freq.count(":") >= 1:
            try:
                next_time = datetime.fromisoformat(freq)
                if next_time.tzinfo is None:
                    next_time = next_time.astimezone()
                return next_time
            except Exception:
                pass
                
        now = datetime.now().astimezone()
        
        if not last_fetched_str:
            # If no last fetched time, run immediately
            return now - timedelta(seconds=1)
            
        last = datetime.fromisoformat(last_fetched_str)
        if last.tzinfo is None:
            last = last.astimezone()
            
        next_time = last
        
        if freq == "每1小时":
            next_time += timedelta(hours=1)
        elif freq == "每6小时":
            next_time += timedelta(hours=6)
        elif freq == "每天 (03:00)":
            next_time += timedelta(days=1)
            next_time = next_time.replace(hour=3, minute=0, second=0, microsecond=0)
        elif freq == "每周一":
            days_ahead = 7 - next_time.weekday()
            if days_ahead == 0:
                days_ahead = 7
            next_time += timedelta(days=days_ahead)
            next_time = next_time.replace(hour=3, minute=0, second=0, microsecond=0)
        elif freq == "每月1号":
            month = next_time.month + 1
            year = next_time.year
            if month > 12:
                month = 1
                year += 1
            next_time = next_time.replace(year=year, month=month, day=1, hour=3, minute=0, second=0, microsecond=0)
        else:
            # Basic heuristics
            if "小时" in freq:
                m = re.search(r"(\d+)小时", freq)
                h = int(m.group(1)) if m else 1
                next_time += timedelta(hours=h)
            elif "天" in freq or "日" in freq:
                next_time += timedelta(days=1)
            elif "周" in freq or "星期" in freq:
                next_time += timedelta(days=7)
            elif "半月" in freq:
                next_time += timedelta(days=15)
            elif "月" in freq:
                next_time = next_time.replace(month=(next_time.month % 12) + 1, year=next_time.year + (1 if next_time.month == 12 else 0))
            elif "季" in freq:
                next_time = next_time.replace(month=(next_time.month + 2) % 12 + 1, year=next_time.year + (1 if next_time.month >= 10 else 0))
            elif "半年" in freq:
                next_time = next_time.replace(month=(next_time.month + 5) % 12 + 1, year=next_time.year + (1 if next_time.month >= 7 else 0))
            elif "年" in freq:
                next_time = next_time.replace(year=next_time.year + 1)
            else:
                return None
                
        return next_time
    except Exception as e:
        logging.error(f"Error calculating time for freq '{freq}': {e}")
        return None

def trigger_crawl(row_id):
    logging.info(f"Triggering background crawl for Row {row_id}...")
    try:
        req = urllib.request.Request(
            API_CRAWL_ROW_URL,
            data=json.dumps({"row": row_id}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=1200) as response:
            res_data = json.loads(response.read().decode())
            if res_data.get("ok"):
                logging.info(f"Row {row_id} crawled successfully.")
            else:
                logging.error(f"Row {row_id} failed: {res_data.get('error')}")
    except Exception as e:
        logging.error(f"Row {row_id} exception during crawl: {e}")

def run_scheduler_cycle():
    try:
        req = urllib.request.Request(API_SCHEDULE_URL)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
            
        rows = data.get("rows", [])
        now = datetime.now().astimezone()
        
        for row in rows:
            row_id = str(row.get("row"))
            freq = row.get("frequency")
            last_fetched = row.get("last_fetched")
            
            next_time = calculate_next_time(last_fetched, freq)
            if not next_time:
                continue
                
            if now >= next_time:
                last_trig = last_triggered.get(row_id)
                # Debounce for 10 minutes
                if not last_trig or (now - last_trig).total_seconds() > 600:
                    logging.info(f"Time to run Row {row_id}. Freq: {freq}, Next expected: {next_time}")
                    last_triggered[row_id] = now
                    threading.Thread(target=trigger_crawl, args=(row_id,), daemon=True).start()
                    
    except Exception as e:
        logging.error(f"Error in scheduler cycle: {e}")

def main():
    logging.info("Starting background scheduler... Polling every 60 seconds.")
    while True:
        run_scheduler_cycle()
        time.sleep(60)

if __name__ == "__main__":
    main()
