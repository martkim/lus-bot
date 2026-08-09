import logging
from datetime import datetime, timezone

from src import db
from src.dto.teachers import TeacherDTO
from src.dto.dashboard import DashboardStatusDTO, ActiveStudentDTO, DailyStatDTO, TimelineEntryDTO
from src.dto.qa import QuestionWithStudentDTO

logger = logging.getLogger("passion_mate")


def get_dashboard_status(teacher: TeacherDTO) -> DashboardStatusDTO:
    """원장(role='director')이면 전체, 파트 담당 선생님이면 자기 파트(instrument) 학생만."""
    logger.info(f"[GET_DASHBOARD_STATUS] 시작 teacher={teacher.username} role={teacher.role}")
    part = None if teacher.role == "director" else teacher.part

    today_local_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_iso = today_local_start.astimezone(timezone.utc).isoformat()

    active_students = [ActiveStudentDTO(**row) for row in db.get_active_sessions_with_students(part=part)]
    daily_stats = [DailyStatDTO(**row) for row in db.get_daily_stats_since(today_start_iso, part=part)]
    timeline = [TimelineEntryDTO(**row) for row in db.get_completed_timeline_since(today_start_iso, part=part)]
    questions = [QuestionWithStudentDTO(**row) for row in db.get_recent_questions_with_student(limit=20, part=part)]

    return DashboardStatusDTO(
        activeStudents=active_students,
        dailyStats=daily_stats,
        timeline=timeline,
        questions=questions,
    )
