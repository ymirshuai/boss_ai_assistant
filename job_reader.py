"""
AI 回复解析与验证模块
功能：从 AI 回复文本中提取岗位 JSON，验证数量和格式，
      通过返回数组，未通过返回错误原因字符串
"""

import json
import re
from typing import Optional, Union


# 必填字段
REQUIRED_FIELDS = [
    "job_title",
    "company",
    "salary",
    "hr_name",
    "hr_title",
    "commute_time",
]


def parse_ai_reply(text: str) -> Union[list[dict], str]:
    """
    从 AI 回复文本中提取并验证岗位 JSON。

    支持以下格式：
    - 纯 JSON 数组: [{"job_title":...}, ...]
    - Markdown 代码块: ```json ... ``` 或 ``` ... ```
    - 包裹了说明文字的回复

    Args:
        text: AI 的回复文本

    Returns:
        验证通过: 返回岗位列表 list[dict]
        验证失败: 返回错误原因字符串
    """
    if not text or not text.strip():
        return "AI 回复内容为空，无法解析"

    # 第一步：从文本中提取 JSON 字符串
    json_str = _extract_json(text)
    if not json_str:
        return f"无法从 AI 回复中提取 JSON。回复内容（前200字）:\n{text[:200]}"

    # 第二步：解析 JSON
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # 尝试修复常见格式问题
        fixed = _try_fix_json(json_str)
        if fixed:
            try:
                data = json.loads(fixed)
            except json.JSONDecodeError:
                return f"JSON 解析失败: {e}\n原始内容（前300字）:\n{json_str[:300]}"
        else:
            return f"JSON 解析失败: {e}\n原始内容（前300字）:\n{json_str[:300]}"

    # 第三步：统一为列表
    jobs = _normalize_to_list(data)
    if isinstance(jobs, str):
        return jobs  # 返回错误信息

    # 第四步：验证
    error = _validate(jobs)
    if error:
        return error

    return jobs


def _extract_json(text: str) -> Optional[str]:
    """
    从文本中提取 JSON 字符串，按优先级尝试：
    1. markdown 代码块（```json ... ```）
    2. 最外层 [...] 数组
    3. 最外层 {...} 对象
    """
    # 方法1：提取 markdown 代码块
    # 支持 ```json ... ``` 和 ``` ... ```
    pattern = r"```(?:json)?\s*\n?(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
    for m in matches:
        stripped = m.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            return stripped

    # 方法2：找最外层的 [...] 数组
    array_result = _extract_balanced_brackets(text, "[", "]")
    if array_result:
        return array_result

    # 方法3：找最外层的 {...} 对象
    obj_result = _extract_balanced_brackets(text, "{", "}")
    if obj_result:
        return obj_result

    return None


def _extract_balanced_brackets(text: str, open_char: str, close_char: str) -> Optional[str]:
    """
    找到文本中第一个完整的最外层括号对（支持嵌套）。
    返回括号内的完整字符串（包含括号），或 None。
    """
    start = text.find(open_char)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(text[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None  # 括号不匹配


def _try_fix_json(s: str) -> Optional[str]:
    """
    尝试修复常见的 JSON 格式问题：
    - 尾部逗号（trailing comma）
    - 单引号替换为双引号
    - 缺少引号的 key
    """
    try:
        # 修复尾部逗号
        fixed = re.sub(r",\s*([}\]])", r"\1", s)
        # 修复单引号（仅当不在字符串内时，简单处理）
        # 这里用 ast.literal_eval 作为后备
        import ast
        parsed = ast.literal_eval(fixed)
        return json.dumps(parsed, ensure_ascii=False)
    except Exception:
        return None


def _normalize_to_list(data) -> Union[list[dict], str]:
    """
    将解析后的数据统一为 list[dict]。
    支持：
    - list: 直接返回
    - dict with "jobs" key: 提取 jobs 值
    - dict: 包裹为 [dict]
    """
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if "jobs" in data and isinstance(data["jobs"], list):
            return data["jobs"]
        # 可能是单个岗位，包裹为列表
        return [data]

    return f"JSON 解析结果类型不支持: {type(data).__name__}，期望 list 或 dict"


def _validate(jobs: list[dict]) -> Optional[str]:
    """
    验证岗位列表。
    返回 None 表示通过，返回 str 表示错误原因。
    """
    if not isinstance(jobs, list):
        return f"岗位数据不是列表类型，实际为: {type(jobs).__name__}"

    count = len(jobs)
    if count < 2:
        return f"岗位数量不足！要求至少 2 个，实际只有 {count} 个。请让 AI 重新识别前 2个岗位。"

    errors = []
    for i, job in enumerate(jobs[:2], start=1):  # 只检查前2个
        if not isinstance(job, dict):
            errors.append(f"  第{i}个不是对象类型，实际为: {type(job).__name__}")
            continue

        missing = [f for f in REQUIRED_FIELDS if f not in job]
        if missing:
            errors.append(f"  第{i}个缺少字段: {missing}")

        empty = [
            f
            for f in REQUIRED_FIELDS
            if f in job
            and (job[f] is None or (isinstance(job[f], str) and job[f].strip() == ""))
        ]
        if empty:
            errors.append(f"  第{i}个存在空值字段: {empty}")

    if errors:
        return "岗位数据格式有误:\n" + "\n".join(errors)

    return None  # 验证通过

