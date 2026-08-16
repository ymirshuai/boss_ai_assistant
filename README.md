# BOSS 直聘 AI 自动回复助手

基于 ADB + 千问 VL 的 BOSS 直聘自动化工具，支持自动浏览岗位、自动打招呼、自动回复消息。

## 📁 项目结构

```
boss_ai_assistant/
├── config.example.py    # 配置模板（真实 config.py 已 gitignore，克隆后 cp 为 config.py）
├── device.py           # 设备管理（ADB 连接、截图、点击）
├── ocr_engine.py       # OCR 引擎（千问 VL 文字提取）
├── intent_classifier.py # 意图分类器（判断是否需要发简历/微信）
├── job_browser.py      # 岗位浏览模块（浏览+打招呼）
├── message_replier.py  # 消息回复模块（回复+发简历/微信）
├── logger.py           # 日志统计（日志记录+统计面板）
├── main.py             # 主程序入口
├── assets/             # 资源文件
│   ├── resume.pdf      # 简历文件
│   └── wechat_qr.png   # 微信二维码
├── logs/               # 日志目录
│   ├── error.log       # 错误日志
│   └── stats.log       # 统计日志
└── Screenshots/        # 截图目录
    ├── job_list.png
    ├── job_detail.png
    └── chat_detail.png
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 本地 GPU OCR（PaddleOCR）依赖见 GPU_SETUP_GUIDE.md，需单独安装 paddlepaddle-gpu==2.6.2.post120
```

### 2. 配置 API Key 与 config

1. 复制配置模板：`cp config.example.py config.py`，按需填入 `device_id` / 坐标 / 私有 MaaS 网关。
2. API Key 放 `Key.json`（参考 `Key.json.example`），或由 `load_key()` 首次运行时交互式输入；**切勿把真实 Key 提交到仓库**。目前 `Key.json` 含 `DASHSCOPE_API_KEY`（模型网关）与 `BARK_KEY`（Bark 手机推送），二者均为敏感信息。

### 3. 获取坐标

用 **AirtestIDE** 获取以下坐标，并填写到 `config.py` 的 `COORDINATES` 中：

- `first_chat_item`: 第一个聊天项坐标
- `input_box`: 输入框坐标
- `send_button`: 发送按钮坐标
- `first_job_card`: 第一个岗位卡片坐标

### 4. 运行

```bash
python main.py
```

## 📋 功能说明

### 主循环

1. 检测新消息
2. 如果有新消息 → 回复消息
3. 如果没有新消息 → 浏览岗位
4. 打印统计面板
5. 等待一段时间，重复

### 浏览岗位

1. 截图识别岗位信息
2. 判断匹配度（基于简历）
3. 如果匹配 → 进入详情页 → 生成打招呼文案 → 发送
4. 如果不匹配 → 跳过

### 回复消息

1. 截图识别消息内容
2. 分类意图（是否需要发简历/微信）
3. 生成回复文案
4. 执行操作（发简历/微信）
5. 发送回复

### 异常处理

- 所有异常都会调用 `handle_exception()`
- 目前先报错，暂停脚本，等人工处理
- 以后接入企业微信推送

## 📊 统计面板

运行时实时显示：

```
==================================================
📊 运行统计
==================================================
⏱️  运行时长：1 小时 30 分钟
👀 浏览岗位：15 个
👋 成功打招呼：8 个
⏭️  跳过（不匹配）：7 个
💬 回复消息：12 条
📄 发送简历：2 次
📱 发送微信：1 次
❌ 异常次数：0 次
==================================================
```

## ⚙️ 配置说明

### config.py

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `QWEN_API_KEY` | 千问 API Key | 请填写 |
| `DEVICE_CONFIG["device_id"]` | 设备 ID | `YOUR_DEVICE_ID` |
| `BEHAVIOR_CONFIG["cooldown_seconds"]` | 同一 BOSS 冷却时间（秒） | `300` |
| `BEHAVIOR_CONFIG["greet_interval"]` | 打招呼最小间隔（秒） | `60` |
| `BEHAVIOR_CONFIG["match_threshold"]` | 岗位匹配度阈值（%） | `70` |

## 📝 TODO

- [ ] 实现 `_check_new_message()` 函数（检测新消息）
- [ ] 实现 `_send_resume()` 函数（发送简历）
- [ ] 实现 `_send_wechat()` 函数（发送微信）
- [ ] 获取所有坐标并填写到 `config.py`
- [ ] 接入企业微信推送（异常处理）
- [ ] 增加更多日志和统计

## ⚠️ 注意事项

1. **遵守 BOSS 直聘用户协议**，自动操作可能违反 ToS
2. **不要高频发送**，每天控制在合理数量
3. **建议加人工确认环节**：AI 生成回复 → 推送到微信 → 你确认后 → 再自动发送
4. **设备需要保持唤醒**：设置 → 开发者选项 → 保持唤醒

## 🐛 常见问题

### 1. ADB 连接不稳定

```bash
adb kill-server
adb start-server
```

### 2. 中文输入失败

安装 **AirtestIDE**，用它的 `text()` 方法。

### 3. 千问 API 调用失败

检查 API Key 是否正确，余额是否充足。

## 📄 许可证

MIT License
