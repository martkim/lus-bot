import sqlite3
import datetime
from pathlib import Path
import os

db_path = Path('database.db')
if not db_path.exists():
    print('DB File Not Found!')
    exit(1)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

print("--- PASSION MATE HEALTH CHECK ---")
# 1. Integrity Check
cursor.execute('PRAGMA integrity_check;')
integrity = cursor.fetchone()[0]
print(f'1. DB Integrity Check: {integrity}')

# 2. Total tables and sizes
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f'2. Tables Found: {[t[0] for t in tables]}')

# 3. DB Size
db_size = os.path.getsize(db_path) / 1024
print(f'3. Database Size: {db_size:.2f} KB')

# 4. Active Sessions Check
try:
    cursor.execute("SELECT id, student_id, start_time FROM sessions WHERE status='ACTIVE'")
    active_sessions = cursor.fetchall()
    print(f'4. Total Active Sessions: {len(active_sessions)}')
    
    stale_sessions = 0
    now = datetime.datetime.now(datetime.timezone.utc)
    for sess in active_sessions:
        s_id, st_id, start_str = sess
        start_time = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=datetime.timezone.utc)
        diff_hours = (now - start_time).total_seconds() / 3600
        if diff_hours > 20:
            stale_sessions += 1
            print(f'  - WARNING: Stale session found (ID: {s_id}, Student: {st_id}, Open for {diff_hours:.1f}h)')
    print(f'   Stale Sessions (>20h): {stale_sessions}')
except Exception as e:
    print(f'Error querying sessions: {e}')

# 5. Check AI API Key
api_key = os.environ.get("GEMINI_API_KEY")
print(f"5. AI Key Ready: {bool(api_key)}")

conn.close()
