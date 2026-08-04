import sqlite3
import datetime
import sys

def main():
    try:
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        print('--- DB Integrity Check ---')
        cursor.execute('PRAGMA integrity_check;')
        integrity = cursor.fetchone()[0]
        print(f'Integrity: {integrity}')

        print('\n--- Ghost Active Sessions (Active > 12h) ---')
        cursor.execute("SELECT id, student_id, start_time FROM sessions WHERE status='ACTIVE'")
        active_sessions = cursor.fetchall()
        ghost_sessions = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for sess in active_sessions:
            start_time_str = sess['start_time'].replace('Z', '+00:00')
            start_dt = datetime.datetime.fromisoformat(start_time_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
            diff_hours = (now - start_dt).total_seconds() / 3600
            if diff_hours > 12:
                ghost_sessions.append((sess['id'], sess['student_id'], diff_hours))
        print(f'Total Active Sessions: {len(active_sessions)}')
        print(f'Ghost Sessions (>12h): {len(ghost_sessions)}')
        for gs in ghost_sessions:
            print(f'  Session ID {gs[0]} for Student {gs[1]} active for {gs[2]:.2f} hours')

        print('\n--- Recent Questions Status ---')
        cursor.execute("SELECT COUNT(*) FROM questions WHERE status='WAITING'")
        waiting_qa = cursor.fetchone()[0]
        print(f'Unanswered Q&A: {waiting_qa}')
        
    except Exception as e:
        print(f"Error checking DB: {e}", file=sys.stderr)

if __name__ == '__main__':
    main()
