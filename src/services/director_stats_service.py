import io
import logging

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference

from src import db

logger = logging.getLogger("passion_mate")


def generate_stats_excel() -> bytes:
    """선생님별 담당 원생 수 요약(표+막대그래프) + 전체 재적생 상세, 두 시트짜리 엑셀 파일을 바이트로 생성."""
    logger.info("[GENERATE_STATS_EXCEL] 시작")
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "선생님별 원생 현황"
    ws1.append(["선생님", "파트", "담당 원생 수"])
    for row in db.get_teacher_student_counts():
        ws1.append([row["display_name"], row["part"], row["student_count"]])

    if ws1.max_row > 1:
        chart = BarChart()
        chart.title = "선생님별 담당 원생 수"
        chart.y_axis.title = "원생 수"
        data = Reference(ws1, min_col=3, min_row=1, max_row=ws1.max_row)
        cats = Reference(ws1, min_col=1, min_row=2, max_row=ws1.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        ws1.add_chart(chart, "E2")

    ws2 = wb.create_sheet("학생 상세")
    ws2.append(["이름", "파트", "나이", "MBTI", "가입 상태"])
    for row in db.get_all_active_students_for_export():
        ws2.append([
            row["name"], row["instrument"], row["age"], row["mbti"] or "-",
            "가입완료" if row["username"] else "미가입",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
