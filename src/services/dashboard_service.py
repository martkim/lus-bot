import logging
from datetime import datetime, timezone

from src import db
from src.dto.dashboard import DashboardStatusDTO, ActiveStudentDTO, DailyStatDTO, TimelineEntryDTO
from src.dto.qa import QuestionWithStudentDTO

logger = logging.getLogger("passion_mate")


def get_dashboard_status() -> DashboardStatusDTO:
    logger.info("[GET_DASHBOARD_STATUS] 시작")
    today_local_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_iso = today_local_start.astimezone(timezone.utc).isoformat()

    active_students = [ActiveStudentDTO(**row) for row in db.get_active_sessions_with_students()]
    daily_stats = [DailyStatDTO(**row) for row in db.get_daily_stats_since(today_start_iso)]
    timeline = [TimelineEntryDTO(**row) for row in db.get_completed_timeline_since(today_start_iso)]
    questions = [QuestionWithStudentDTO(**row) for row in db.get_recent_questions_with_student(limit=20)]

    return DashboardStatusDTO(
        activeStudents=active_students,
        dailyStats=daily_stats,
        timeline=timeline,
        questions=questions,
    )
