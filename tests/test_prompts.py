"""提示词配置加载测试（不依赖 qwen_agent / 网络）。"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_prompts_yaml_loads():
    data = yaml.safe_load((ROOT / "prompts.yaml").read_text(encoding="utf-8"))
    assert "system" in data
    assert "prompts" in data
    expected = {
        "extract_job_info",
        "extract_job_jd",
        "check_new_job",
        "generate_reply",
        "match_job",
        "extract_which_job",
    }
    assert expected.issubset(set(data["prompts"].keys()))


def test_config_mode_default_valid():
    # 仅校验默认值合法，不触发 config 的 load_key 副作用
    import os

    mode = os.environ.get("BOSS_MODE", "auto")
    assert mode in ("auto", "agent")
