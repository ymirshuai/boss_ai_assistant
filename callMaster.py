
import os
import requests
from urllib.parse import quote


def call_master(title, content, key=None):
    """
    通过 Bark（api.day.app）向手机推送通知。
    key 为 Bark 服务端 key，属于敏感信息，必须从环境变量 BARK_KEY 读取，
    不要硬编码在此文件。来源：Key.json -> load_key() 注入 os.environ["BARK_KEY"]。
    """
    key = key or os.environ.get("BARK_KEY")
    if not key:
        raise ValueError(
            "未配置 Bark 推送 key。请在 Key.json 中加入 \"BARK_KEY\": \"你的key\"，"
            "或由 load_key() 注入环境变量 BARK_KEY。"
        )
    # 路径段必须 URL 编码，否则中文/空格/特殊字符会请求失败
    url = f"https://api.day.app/{key}/{quote(title)}/{quote(content)}"
    requests.get(url).raise_for_status()
