# data_store.py
# 数据持久化模块（SQLite + 向量库）
# 用于保存岗位信息和聊天记录

import sqlite3
import json
from pathlib import Path

# 数据库文件路径
DB_PATH = Path(__file__).parent / "boss_ai_assistant.db"


def init_db():
    """
    初始化数据库，创建必要的表
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # 创建岗位信息表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_title TEXT,          -- 岗位名称
            company TEXT,            -- 公司名称
            salary TEXT,             -- 薪资范围
            hr_name TEXT,           -- 招聘者姓名
            hr_title TEXT,          -- 招聘者职位
            commute_time TEXT,      -- 通勤时间
            job_jd TEXT,           -- 岗位职责
            job_requirements TEXT,  -- 任职要求
            home_distance TEXT,     -- 离家距离
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 创建聊天记录表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,         -- 关联的岗位ID
            message TEXT,           -- 消息内容
            sender TEXT,            -- 发送者 ('me' 或 'hr')
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)

    # 创建用户信息表（模拟 HR 对话中采集到的候选人信息）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,          -- 信息类别，如 "基本信息"/"求职期望"/"技能"
            field_name TEXT,        -- 字段名
            field_value TEXT,       -- 字段值
            source TEXT,            -- 来源，如 "HR对话模拟"/"简历"
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建每日运行统计表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,          -- 运行会话ID（同一进程的多次调用共享）
            stat_date DATE,           -- 统计日期（print_stats 调用当天）
            recorded_at TIMESTAMP,    -- 记录时间
            browse_count INTEGER,     -- 浏览岗位数
            greet_count INTEGER,      -- 打招呼数
            skip_count INTEGER,       -- 跳过数
            reply_count INTEGER,      -- 回复消息数
            resume_sent INTEGER,      -- 发送简历次数
            wechat_sent INTEGER,      -- 发送微信次数
            error_count INTEGER,      -- 异常次数
            elapsed_seconds REAL      -- 本次会话累计运行时长（秒）
        )
    """)

    conn.commit()
    conn.close()
    print(f"✅ 数据库初始化完成：{DB_PATH}")


def save_job_info(job_info):
    """
    保存岗位信息
    :param job_info: 字典，包含岗位信息
        {
            "job_title": "岗位名称",
            "company": "公司名称",
            "salary": "薪资范围",
            "hr_name": "招聘者姓名",
            "hr_title": "招聘者职位",
            "commute_time": "通勤时间",
            "job_jd": "岗位职责",
            "job_requirements": "任职要求",
            "home_distance": "离家距离"
        }
    :return: job_id (新插入的岗位ID)
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # 检查是否已存在相同公司和HR的岗位
    cursor.execute("""
        SELECT id FROM jobs 
        WHERE company = ? AND hr_name = ?
    """, (job_info.get("company"), job_info.get("hr_name")))
    
    existing_job = cursor.fetchone()
    
    if existing_job:
        # 更新现有记录
        job_id = existing_job[0]
        cursor.execute("""
            UPDATE jobs 
            SET job_title = ?,
                salary = ?,
                hr_title = ?,
                commute_time = ?,
                job_jd = ?,
                job_requirements = ?,
                home_distance = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            job_info.get("job_title"),
            job_info.get("salary"),
            job_info.get("hr_title"),
            job_info.get("commute_time"),
            job_info.get("job_jd"),
            job_info.get("job_requirements"),
            job_info.get("home_distance"),
            job_id
        ))
        print(f"✅ 更新岗位信息：{job_info.get('company')} - {job_info.get('hr_name')}")
    else:
        # 插入新记录
        cursor.execute("""
            INSERT INTO jobs (
                job_title, company, salary, hr_name, hr_title,
                commute_time, job_jd, job_requirements, home_distance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_info.get("job_title"),
            job_info.get("company"),
            job_info.get("salary"),
            job_info.get("hr_name"),
            job_info.get("hr_title"),
            job_info.get("commute_time"),
            job_info.get("job_jd"),
            job_info.get("job_requirements"),
            job_info.get("home_distance")
        ))
        job_id = cursor.lastrowid
        print(f"✅ 保存新岗位：{job_info.get('company')} - {job_info.get('hr_name')}")
    
    conn.commit()
    conn.close()
    return job_id


def save_chat_record(job_id, message, sender):
    """
    保存聊天记录
    :param job_id: 关联的岗位ID
    :param message: 消息内容
    :param sender: 发送者 ('me' 或 'hr')
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO chat_history (job_id, message, sender)
        VALUES (?, ?, ?)
    """, (job_id, message, sender))
    
    conn.commit()
    conn.close()
    print(f"✅ 保存聊天记录：{message[:50]}...")


def save_user_info(items):
    """
    保存从 HR 对话中提取的用户（候选人）信息。

    :param items: 列表，每项形如
        {"category": "求职期望", "field_name": "期望薪资",
         "field_value": "20-30K", "source": "HR对话模拟"}
        其中 source 可选，默认 "HR对话模拟"。
    :return: (inserted, updated) 计数元组
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    inserted = updated = 0
    for it in items or []:
        category = it.get("category")
        field_name = it.get("field_name")
        field_value = it.get("field_value")
        source = it.get("source", "HR对话模拟")
        if not field_name:
            continue
        cursor.execute(
            "SELECT id FROM user_info WHERE category IS ? AND field_name = ?",
            (category, field_name),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE user_info SET field_value = ?, source = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (field_value, source, row[0]),
            )
            updated += 1
        else:
            cursor.execute(
                "INSERT INTO user_info (category, field_name, field_value, source) VALUES (?, ?, ?, ?)",
                (category, field_name, field_value, source),
            )
            inserted += 1
    conn.commit()
    conn.close()
    return inserted, updated


def get_user_info(category=None):
    """
    读取用户（候选人）信息；category 为空则返回全部。
    :return: 列表，每项为 {category, field_name, field_value, source, created_at}
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    if category:
        cursor.execute(
            "SELECT category, field_name, field_value, source, created_at "
            "FROM user_info WHERE category = ? ORDER BY id",
            (category,),
        )
    else:
        cursor.execute(
            "SELECT category, field_name, field_value, source, created_at "
            "FROM user_info ORDER BY id"
        )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "category": r[0],
            "field_name": r[1],
            "field_value": r[2],
            "source": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


def get_job_by_company_hr(company, hr_name):
    """
    根据公司名和HR姓名查询岗位信息
    :param company: 公司名称
    :param hr_name: 招聘者姓名
    :return: 岗位信息字典，如果不存在返回 None
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM jobs 
        WHERE company = ? AND hr_name = ?
    """, (company, hr_name))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        # 将行数据转换为字典
        columns = ["id", "job_title", "company", "salary", "hr_name", 
                   "hr_title", "commute_time", "job_jd", "job_requirements", 
                   "home_distance", "created_at", "updated_at"]
        job_info = dict(zip(columns, row))
        return job_info
    else:
        return None


def get_chat_history(job_id):
    """
    获取指定岗位的聊天记录
    :param job_id: 岗位ID
    :return: 聊天记录列表
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT message, sender, timestamp 
        FROM chat_history 
        WHERE job_id = ?
        ORDER BY timestamp
    """, (job_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    chat_history = []
    for row in rows:
        chat_history.append({
            "message": row[0],
            "sender": row[1],
            "timestamp": row[2]
        })
    
    return chat_history


def get_all_jobs():
    """
    获取所有岗位信息
    :return: 岗位信息列表
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM jobs ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    jobs = []
    columns = ["id", "job_title", "company", "salary", "hr_name", 
                "hr_title", "commute_time", "job_jd", "job_requirements", 
                "home_distance", "created_at", "updated_at"]
    
    for row in rows:
        jobs.append(dict(zip(columns, row)))
    
    return jobs


def export_to_json():
    """
    导出所有数据为 JSON 文件（备份用）
    """
    jobs = get_all_jobs()
    
    export_data = []
    for job in jobs:
        job_id = job["id"]
        chat_history = get_chat_history(job_id)
        
        export_data.append({
            "job_info": job,
            "chat_history": chat_history
        })
    
    # 保存到 JSON 文件
    export_path = Path(__file__).parent / "data_backup.json"
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 数据已导出到：{export_path}")


def save_daily_stats(session_id, stats, elapsed_seconds):
    """
    保存一次运行统计快照到 daily_stats 表
    :param session_id: 运行会话ID（同一次运行实例共享，用于区分多次启动）
    :param stats: Logger.stats 字典（累积计数）
    :param elapsed_seconds: 本次会话累计运行时长（秒）
    """
    from datetime import datetime

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    now = datetime.now()
    stat_date = now.strftime("%Y-%m-%d")
    recorded_at = now.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO daily_stats (
            session_id, stat_date, recorded_at,
            browse_count, greet_count, skip_count, reply_count,
            resume_sent, wechat_sent, error_count, elapsed_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id, stat_date, recorded_at,
        stats.get("browse_count", 0),
        stats.get("greet_count", 0),
        stats.get("skip_count", 0),
        stats.get("reply_count", 0),
        stats.get("resume_sent", 0),
        stats.get("wechat_sent", 0),
        stats.get("error_count", 0),
        elapsed_seconds,
    ))

    conn.commit()
    conn.close()


def get_daily_summary(date_str=None):
    """
    汇总每日运行统计。
    每个会话在同一天可能产生多条快照（print_stats 被多次调用），
    取每个 (stat_date, session_id) 最新一条（自增 id 最大）作为该会话当日总量，
    再按日期求和，从而正确处理「一天内多次启动/跨午夜」等情况。

    :param date_str: 指定日期 'YYYY-MM-DD'；为 None 时返回所有日期
    :return: 列表，按日期倒序，每项为当日汇总字典
    """
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    if date_str:
        cursor.execute(
            "SELECT * FROM daily_stats WHERE stat_date = ? ORDER BY id",
            (date_str,)
        )
    else:
        cursor.execute("SELECT * FROM daily_stats ORDER BY id")

    rows = cursor.fetchall()
    conn.close()

    columns = [
        "id", "session_id", "stat_date", "recorded_at",
        "browse_count", "greet_count", "skip_count", "reply_count",
        "resume_sent", "wechat_sent", "error_count", "elapsed_seconds",
    ]
    numeric_keys = [
        "browse_count", "greet_count", "skip_count", "reply_count",
        "resume_sent", "wechat_sent", "error_count", "elapsed_seconds",
    ]

    # 取每个 (stat_date, session_id) 的最新一条快照
    # 用自增 id 作为去重依据（避免同一秒内 recorded_at 相同导致的歧义）
    latest = {}
    for row in rows:
        rec = dict(zip(columns, row))
        key = (rec["stat_date"], rec["session_id"])
        if key not in latest or rec["id"] > latest[key]["id"]:
            latest[key] = rec

    # 按日期求和
    summary = {}
    for rec in latest.values():
        d = rec["stat_date"]
        if d not in summary:
            summary[d] = {k: 0 for k in numeric_keys}
            summary[d]["stat_date"] = d
        for k in numeric_keys:
            summary[d][k] += rec[k]

    # 转列表并按日期倒序返回
    return [summary[d] for d in sorted(summary.keys(), reverse=True)]


def get_today_greet_count():
    """
    读取当日成功打招呼总数
    取当天每个会话最新一条快照（自增 id 最大）的 greet_count 再求和，
    返回 int。若当日无数据则返回 0。
    :return: int，当日累计成功打招呼数
    """
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, session_id, greet_count FROM daily_stats "
        "WHERE stat_date = ? ORDER BY id",
        (today,)
    )
    rows = cursor.fetchall()
    conn.close()

    # 取每个会话当日最新一条快照，再求和
    latest = {}
    for row_id, session_id, greet_count in rows:
        if session_id not in latest or row_id > latest[session_id][0]:
            latest[session_id] = (row_id, greet_count)

    return int(sum(v[1] for v in latest.values()))


# 初始化数据库（模块加载时自动执行）
init_db()

if __name__ == "__main__":
    # 测试代码
    print("🧪 测试数据持久化模块...")
    
    # 测试保存岗位信息
    test_job = {
        "job_title": "Python开发工程师",
        "company": "测试公司",
        "salary": "15-25K",
        "hr_name": "张女士",
        "hr_title": "招聘经理",
        "commute_time": "30分钟",
        "job_jd": "负责后端开发",
        "job_requirements": "3年以上经验",
        "home_distance": "5公里"
    }
    
    job_id = save_job_info(test_job)
    print(f"   岗位ID：{job_id}")
    
    # 测试保存聊天记录
    save_chat_record(job_id, "你好，我对这个职位感兴趣", "me")
    save_chat_record(job_id, "你好，方便了解一下你的经验吗？", "hr")
    
    # 测试查询
    job_info = get_job_by_company_hr("测试公司", "张女士")
    print(f"   查询结果：{job_info}")
    
    # 测试获取聊天记录
    chat_history = get_chat_history(job_id)
    print(f"   聊天记录：{chat_history}")
    
    # 导出数据
    export_to_json()
    
    print("✅ 测试完成")
