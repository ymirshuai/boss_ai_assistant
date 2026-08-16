"""
提示词加载器（统一接缝）

所有模块从这里取提示词，不再散读 config.PROMPTS / system_prompt.txt。
prompts.yaml 的变更通过 lru_cache 只加载一次。
"""
import functools
from pathlib import Path
from string import Template

import yaml

_PROMPTS_YAML = Path(__file__).parent / "prompts.yaml"


@functools.lru_cache(maxsize=1)
def load_prompts() -> dict:
    return yaml.safe_load(_PROMPTS_YAML.read_text(encoding="utf-8"))


def get_prompt(name: str, **kwargs) -> str:
    """取 prompts.<name>；若传入 kwargs，用 $占位符 填充（string.Template）。

    用 $占位符 而非 .format()：提示词里常有 JSON 示例的 { } 字面量，
    .format 会误把它们当占位符而报错；Template 只对 $var 做替换，字面 { } 安全。
    """
    tpl = load_prompts()["prompts"][name]
    if not kwargs:
        return tpl
    return Template(tpl).safe_substitute(**kwargs)


def get_system_prompt() -> str:
    return load_prompts().get("system", "")


def get_knowledge() -> dict:
    return load_prompts().get("knowledge", {})


def update_prompt(name: str, text: str) -> tuple:
    """修改 prompts.yaml 中的某个提示词并持久化，同时清空缓存使其立即生效。

    :param name: 提示词键。可为 "system"（系统提示词）或 prompts.<name>
                 中的某个具体键（如 extract_job_jd / check_new_job）。
    :param text: 新的提示词内容。
    :return: (ok: bool, msg: str)
    """
    path = _PROMPTS_YAML
    raw = path.read_text(encoding="utf-8")

    # 保留文件顶部连续的注释说明（如「占位符用 $var」指引）
    leading = []
    for line in raw.splitlines():
        if line.lstrip().startswith("#"):
            leading.append(line)
        else:
            break

    data = yaml.safe_load(raw) or {}
    if name == "system":
        data["system"] = text
    elif name in data.get("prompts", {}):
        data["prompts"][name] = text
    else:
        avail = "system, " + ", ".join(data.get("prompts", {}).keys())
        return False, f"未知提示词键：{name}（可用：{avail}）"

    dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.write_text("\n".join(leading) + "\n" + dumped, encoding="utf-8")
    load_prompts.cache_clear()
    return True, f"已更新提示词：{name}"
