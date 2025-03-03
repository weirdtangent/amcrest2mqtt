from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo

def app_log(msg, level='INFO', tz='UTC', hide_ts=False):
    ts = datetime.now(ZoneInfo(tz)).strftime('%Y-%m-%d %H:%M:%S %Z')
    if len(msg) > 102400:
        raise ValueError('Log message exceeds max length')
    if level != 'DEBUG' or os.getenv('DEBUG'):
        print(f'{ts + " " if not hide_ts else ""}[{level}] {msg}')

def to_gb(total):
    return str(round(float(total[0]) / 1024 / 1024 / 1024, 2))
