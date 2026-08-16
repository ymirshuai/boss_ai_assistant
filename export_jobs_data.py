# export_jobs_data.py
# 从 boss_ai_assistant.db 的 jobs 表单独读取岗位信息，
# 导出为 AI 易读的结构化 JSON（含字段说明 glossary）。
# 用法：python export_jobs_data.py [输出路径，默认 jobs_data.json]

import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "boss_ai_assistant.db"

# 导出字段与中文释义（glossary，供 AI / 人工理解）
FIELD_GLOSSARY = {
    "id": "岗位记录 ID（主键）",
    "company": "公司名称",
    "job_title": "岗位名称",
    "hr_name": "招聘者姓名",
    "hr_title": "招聘者职位",
    "salary": "薪资范围",
    "commute_time": "通勤时间",
    "home_distance": "离家距离",
    "job_jd": "岗位职责（注：本项目多数记录为空，真实 JD 内容见 job_requirements）",
    "job_requirements": "任职要求 / 岗位 JD 正文",
    "created_at": "入库时间",
    "updated_at": "最近更新时间",
}

# 读取顺序
COLUMNS = [
    "id", "company", "job_title", "hr_name", "hr_title",
    "salary", "commute_time", "home_distance",
    "job_jd", "job_requirements", "created_at", "updated_at",
]


def read_jobs():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT {} FROM jobs ORDER BY id".format(", ".join(COLUMNS))
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def export(output_path=None):
    output_path = Path(output_path) if output_path else (
        Path(__file__).parent / "jobs_data.json"
    )
    jobs = read_jobs()

    payload = {
        "source": "boss_ai_assistant.db / jobs",
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(jobs),
        "fields": FIELD_GLOSSARY,
        "jobs": jobs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"✅ 已导出 {len(jobs)} 条岗位到：{output_path}")
    return output_path


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else None
    export(out)
