import logging
from datetime import datetime, timezone

from src import db

logger = logging.getLogger("passion_mate")


async def auto_cleanup_ghost_sessions():
    try:
        active_sessions = db.get_all_active_sessions()

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        for sess in active_sessions:
            start_time_str = sess["start_time"].replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(start_time_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            diff_hours = (now_dt - start_dt).total_seconds() / 3600

            if diff_hours >= 20:
                # 20시간 초과 시 강제 종료 처리 (최대 1200분으로 제한)
                db.close_ghost_session(sess["id"], now_iso, duration_minutes=1200)
                print(f"[Ghost Session Cleanup] Session {sess['id']} automatically closed (exceeded 20 hours).")
    except Exception as e:
        logger.exception("고스트 세션 정리 실패")
        print(f"[Ghost Session Cleanup Error] {e}")
