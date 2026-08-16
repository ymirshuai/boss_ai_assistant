"""
本地 OCR 引擎（非 LLM）

使用 PaddleOCR 对 BOSS 直聘岗位详情截图做文字识别，
再基于「布局坐标 + 关键词 + 正则」规则把字段抽取出来，
整个过程不调用任何大模型。

主要接口：
    engine = LocalOCREngine()
    job_info = engine.extract_job_info_from_screenshots([img1, img2, ...])

返回字典字段（与现有数据库 / job_info 结构对齐）：
    job_title / company / salary / hr_name / hr_title
    / job_JD / job_requirements / home_distance
未识别到的字段统一返回字符串 "未识别到"。
"""

import os
import re
from typing import Dict, List, Optional

# PaddleOCR 延迟导入，避免在没有 OCR 依赖的环境里 import 本模块直接报错。
_PaddleOCR = None


def _get_paddleocr():
    global _PaddleOCR
    if _PaddleOCR is None:
        from paddleocr import PaddleOCR
        _PaddleOCR = PaddleOCR
    return _PaddleOCR


def _ensure_cuda_on_path():
    """GPU 模式下，把 CUDA 的 bin 目录加入 PATH，保证 paddle 能找到 cudart/cudnn。

    扫描常见盘符与 CUDA 版本目录，命中第一个存在的即注入，避免调用方每次手动配 PATH。
    仅在 Windows + use_gpu 时有意义；找不到也不报错（交给 paddle 自己报错）。
    """
    if "CUDA_BIN_INJECTED" in os.environ:
        return
    os.environ["CUDA_BIN_INJECTED"] = "1"
    drives = ("C", "D", "E", "F", "G")
    versions = ("v12.0", "v11.8", "v11.7", "v12.1", "v12.2")
    for d in drives:
        for v in versions:
            cand = rf"{d}:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\{v}\bin"
            if os.path.isdir(cand) and cand not in os.environ.get("PATH", ""):
                os.environ["PATH"] = cand + os.pathsep + os.environ["PATH"]
                return


class LocalOCREngine:
    def __init__(self, use_gpu: bool = False, logger=None):
        self.logger = logger
        self.use_gpu = use_gpu
        self._ocr = None
        self._cache = {}  # image_path -> 文字块列表

    # ------------------------------------------------------------------ #
    # 初始化 / OCR
    # ------------------------------------------------------------------ #
    def _ensure_ocr(self):
        if self._ocr is None:
            if self.use_gpu:
                _ensure_cuda_on_path()
            PaddleOCR = _get_paddleocr()
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang="ch",
                use_gpu=self.use_gpu,
                show_log=False,
            )
        return self._ocr

    def ocr_image(self, image_path: str, force: bool = False) -> List[Dict]:
        """对单张图做 OCR，返回标准文字块列表。"""
        if (not force) and image_path in self._cache:
            return self._cache[image_path]
        ocr = self._ensure_ocr()
        result = ocr.ocr(image_path, cls=True)
        blocks = []
        if result and result[0]:
            for line in result[0]:
                box = line[0]
                text = line[1][0]
                score = line[1][1]
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                blocks.append(
                    {
                        "text": text.strip(),
                        "score": float(score),
                        "x": float(min(xs)),
                        "y": float(min(ys)),
                        "cx": float(sum(xs) / 4),
                        "cy": float(sum(ys) / 4),
                        "w": float(max(xs) - min(xs)),
                        "h": float(max(ys) - min(ys)),
                    }
                )
        self._cache[image_path] = blocks
        return blocks

    @staticmethod
    def _image_size(image_path: str):
        import cv2

        img = cv2.imread(image_path)
        if img is None:
            return None, None
        h, w = img.shape[:2]
        return w, h

    # ------------------------------------------------------------------ #
    # 跨图去重（顶部标题栏 / 底部按钮会重复出现在多张截图里，保留首屏）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _dedup(raw_blocks: List[Dict]) -> List[Dict]:
        seen = set()
        out = []
        for b in raw_blocks:
            t = b["text"]
            if not t:
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(b)
        return out

    # ------------------------------------------------------------------ #
    # 字段提取
    # ------------------------------------------------------------------ #
    def extract_job_info_from_screenshots(self, image_paths: List[str]) -> Dict:
        """输入 3-8 张连续截图路径（按翻阅顺序），返回单个 job_info dict。"""
        if not image_paths:
            return self._empty()

        # 1) 逐张 OCR，附上所属截图序号（用于阅读顺序 & 区域判断）
        raw = []
        for idx, p in enumerate(image_paths):
            for b in self.ocr_image(p):
                b = dict(b)
                b["src"] = idx
                raw.append(b)

        # 2) 跨图去重
        blocks = self._dedup(raw)

        # 3) 字段解析
        return self._extract_fields(blocks, image_paths)

    # 聊天窗口顶部 crop 抽取（HR 名字 / 公司 / 职位）
    # 适用场景：BOSS IM 聊天顶部裁剪图，布局为
    #   [HR name 大字] [在线 / 忙碌 / 离线 badge]
    #   [公司 · 职位]
    # 与详情页布局不同（无 JD / 薪资 / 任职要求），故单独写。
    def extract_chat_header_info(self, image_path: str) -> Dict:
        blocks = self.ocr_image(image_path)
        W, H = self._image_size(image_path) or (1080, 2340)
        return self._extract_chat_header_from_blocks(blocks, W, H)

    @staticmethod
    def _extract_chat_header_from_blocks(blocks, W, H):
        company = "未识别到"
        hr_name = "未识别到"
        hr_title = "未识别到"
        status_kw = ("在线", "忙碌", "离线")

        badge = None
        for b in blocks:
            if any(k in b["text"] for k in status_kw) and b["y"] <= 0.45 * H:
                badge = b
                break

        if badge is not None:
            cands = [
                b for b in blocks
                if abs(b["y"] - badge["y"]) <= 0.06 * H
                and b["cx"] < badge["cx"]
                and 2 <= len(b["text"]) <= 6
                and re.search(r"[\u4e00-\u9fff]", b["text"])
                and not any(k in b["text"] for k in status_kw)
            ]
            if cands:
                hr_name = max(cands, key=lambda b: b["cx"])["text"]

        if hr_name == "未识别到":
            top = [
                b for b in blocks
                if b["y"] <= 0.30 * H
                and 2 <= len(b["text"]) <= 6
                and re.search(r"[\u4e00-\u9fff]", b["text"])
                and not any(k in b["text"] for k in status_kw)
            ]
            if top:
                hr_name = max(top, key=lambda b: b["w"] * b["h"])["text"]

        for b in blocks:
            if "·" in b["text"]:
                parts = [p.strip() for p in b["text"].split("·")]
                if not parts or not parts[0]:
                    continue
                company = parts[0].rstrip(".。…· ")
                if len(parts) >= 2:
                    hr_title = "·".join(parts[1:]).strip()
                break

        return {"company": company, "hr_name": hr_name, "hr_title": hr_title}

    def _empty(self) -> Dict:
        return {
            "job_title": "未识别到",
            "company": "未识别到",
            "salary": "未识别到",
            "hr_name": "未识别到",
            "hr_title": "未识别到",
            "job_JD": "未识别到",
            "job_requirements": "未识别到",
            "home_distance": "未识别到",
        }

    def _extract_fields(self, blocks: List[Dict], image_paths: List[str]) -> Dict:
        W, H = self._image_size(image_paths[0]) or (1080, 2340)
        first_blocks = [b for b in blocks if b["src"] == 0]

        job_title = self._extract_title(first_blocks, H)
        salary = self._extract_salary(blocks, H)
        hr_name, company, hr_title = self._extract_hr(first_blocks, blocks, H)
        home_distance = self._extract_home_distance(blocks)
        job_jd, job_req = self._extract_jd_req(blocks, H, job_title)

        return {
            "job_title": job_title,
            "company": company,
            "salary": salary,
            "hr_name": hr_name,
            "hr_title": hr_title,
            "job_JD": job_jd,
            "job_requirements": job_req,
            "home_distance": home_distance,
        }

    # ----------------------- 岗位标题 ----------------------- #
    def _extract_title(self, first_blocks, H):
        """
        BOSS 详情页标题在首屏顶部。规则：
        1) 候选 = 顶部区域内、且不是 状态栏/薪资/HR 的块；
        2) 取 y 最靠上的一簇（允许两行标题），按 x 从左到右合并，
           这样既能拿到「高级AI应用工程师 (Agent/RAG/LLM)」完整标题，
           又不会只抓到括号里的技能标签。
        """
        blacklist = ("BOSS", "直聘", "返回", "沟通", "职位", "搜索", "我的")
        cand = []
        for b in first_blocks:
            t = b["text"]
            if not (0.04 * H <= b["y"] <= 0.25 * H):
                continue
            if any(w in t for w in blacklist):
                continue
            if self._is_salary(t):
                continue
            # HR 卡片：含「·」或以 女士/先生/老师 结尾
            if "·" in t or re.search(r"(女士|先生|小姐|老师)$", t):
                continue
            cand.append(b)
        if not cand:
            return "未识别到"
        cand.sort(key=lambda b: b["y"])
        top_y = cand[0]["y"]
        # 取顶部同一簇（两行内），按 x 合并
        cluster = [b for b in cand if b["y"] - top_y <= 0.06 * H]
        cluster.sort(key=lambda b: b["cx"])
        title = "".join(b["text"] for b in cluster).strip()
        title = self._clean_title(title)
        return title or "未识别到"

    @staticmethod
    def _clean_title(title: str) -> str:
        # 去掉 OCR 误粘的装饰符（箭号、星标、全角 G 等）
        strip_set = "《》‹›☆★・·•●ＧG<>"
        title = title.strip()
        title = title.strip(strip_set)
        # 兜底：去掉开头/结尾连续的非「中文/字母/数字」字符
        title = re.sub(r"^[^\u4e00-\u9fffA-Za-z0-9]+", "", title)
        title = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+$", "", title)
        return title.strip()

    # ----------------------- 薪资 ----------------------- #
    @staticmethod
    def _is_salary(text: str) -> bool:
        return bool(
            re.search(
                r"\d+\s*[-~]\s*\d+\s*[kK]"
                r"|[\d.]+\s*[-~]\s*[\d.]+\s*元"
                r"|[\d.]+\s*[-~]\s*[\d.]+\s*万"
                r"|^\d+\s*[kK]$",
                text,
            )
        )

    def _extract_salary(self, blocks, H):
        cands = [b for b in blocks if self._is_salary(b["text"]) and b["y"] <= 0.35 * H]
        if not cands:
            cands = [b for b in blocks if self._is_salary(b["text"])]
        if not cands:
            return "未识别到"
        # 优先顶部、靠右、置信度高的
        cands.sort(key=lambda b: (b["y"], -b["cx"], -b["score"]))
        return cands[0]["text"]

    # ----------------------- HR 信息 ----------------------- #
    def _extract_hr(self, first_blocks, blocks, H):
        hr_name = "未识别到"
        company = "未识别到"
        hr_title = "未识别到"

        title_kw = [
            "招聘", "HR", "主管", "经理", "总监", "专家", "工程师",
            "专员", "总裁", "负责人", "顾问", "猎头", "人事",
            "ceo", "CEO", "HRBP", "BP", "hr",
        ]
        _DEGREE = ("本科", "硕士", "大专", "博士", "学历", "中专")

        # 1) 先定位 HR 卡片第二行：「公司·职位」，含 · 且命中职位关键词
        hr_line = None
        for b in first_blocks:
            if (
                "·" in b["text"]
                and 0.15 * H <= b["y"] <= 0.35 * H
                and any(k in b["text"] for k in title_kw)
            ):
                hr_line = b
                break

        # 2) 公司 / 职位：从「公司·职位」行拆出
        raw_company = ""
        if hr_line is not None:
            parts = [p.strip() for p in hr_line["text"].split("·")]
            raw_company = parts[0]
            for i in range(1, len(parts)):
                if any(k in parts[i] for k in title_kw):
                    company = raw_company.rstrip(".。…· ")
                    hr_title = "·".join(parts[i:]).strip()
                    break
            if hr_title == "未识别到":
                company = raw_company.rstrip(".。…· ")
                hr_title = "·".join(parts[1:]).strip()

        # 2.1) 公司名补全：HR 卡片里的长公司名常被 App 用 .. 截断，
        #      从全部文字块里找以它为前缀、且无 · 的完整公司名替换。
        if raw_company.endswith("..") or raw_company.endswith("…"):
            prefix = raw_company.rstrip(".…")
            for b in blocks:
                t = b["text"]
                if (
                    t.startswith(prefix)
                    and len(t) > len(company)
                    and not t.endswith("..")
                    and not t.endswith("…")
                    and "·" not in t
                ):
                    company = t
                    break

        # 3) HR 姓名：优先取 hr_line 正上方最近的短文本块
        #    （BOSS 姓名常为「阎琳琳」这类不带 honorific 的纯姓名）
        if hr_line is not None:
            for b in sorted(first_blocks, key=lambda x: -x["y"]):
                if b is hr_line:
                    continue
                if b["y"] < hr_line["y"] and hr_line["y"] - b["y"] <= 0.10 * H:
                    t = b["text"]
                    if "·" in t or self._is_salary(t) or t in _DEGREE:
                        continue
                    # 必须是真实姓名：含中文且长度>=2，排除 > < ☆ 等装饰符
                    if len(t) < 2 or not re.search(r"[\u4e00-\u9fff]", t):
                        continue
                    if len(t) <= 6:
                        hr_name = t
                        break

        # 4) 兜底：以 女士/先生/小姐/老师 结尾的短块
        if hr_name == "未识别到":
            for b in first_blocks:
                if re.search(r"(女士|先生|小姐|老师)$", b["text"]) and len(b["text"]) <= 6:
                    hr_name = b["text"]
                    break

        return hr_name, company, hr_title

    # ----------------------- 离家距离 ----------------------- #
    @staticmethod
    def _extract_home_distance(blocks):
        # 只返回正则命中的「距离…X千米」片段，去掉 OCR 把上一行粘连进来的前导标点
        pat = re.compile(r"距离.{0,15}?[\d.]+\s*(?:千米|公里|km|KM|米)")
        for b in blocks:
            m = pat.search(b["text"])
            if m:
                return m.group(0).strip()
        return "未识别到"

    # ----------------------- JD / 任职要求 ----------------------- #
    @staticmethod
    def _ordered_texts(blocks):
        ordered = sorted(blocks, key=lambda b: (b["src"], b["y"]))
        return [b["text"] for b in ordered]

    @staticmethod
    def _find_header(texts, keyword):
        for i, t in enumerate(texts):
            if keyword in t and len(t) <= len(keyword) + 6:
                return i
        # 宽松匹配：含关键词且较短
        for i, t in enumerate(texts):
            if keyword in t and len(t) <= 14:
                return i
        return -1

    @staticmethod
    def _find_first_containing(texts, keyword):
        """返回首个包含 keyword 的文本块下标（不限长度），找不到返回 -1。"""
        for i, t in enumerate(texts):
            if keyword in t:
                return i
        return -1

    # ----------------------- JD / 任职要求 ----------------------- #
    # 这些词出现后，说明已经离开了「岗位职责 / 任职要求」正文区，
    # 后面是 福利 / 公司介绍 / 地图 / 竞争力分析 / 安全提示 等无关内容，必须截断。
    _STOP_KW = (
        "员工福利", "公司介绍", "公司信息", "工商信息", "工作地址",
        "BOSS安全提示", "你的竞争力分析", "查看详细", "申请职位",
        "举报", "分享", "职位描述", "融资", "立即沟通", "加分",
    )

    def _cut_segment(self, blocks, start, end, H, title_head):
        """取 [start+1, end) 区间内的块文本，遇到以下情况立即截断：
        1) 命中停止词（福利/安全提示/…）；
        2) 上一句已结束（以。！？结尾）且本块不是新的编号项 → 通常是翻页后
           置顶重复的岗位标题或「立即沟通」按钮；
        3) 进入底部按钮区（y > 0.86H）。
        若本块是置顶标题的重复（含 title_head），最多跳过 2 次继续。
        """
        if start == -1:
            return "未识别到"
        if end == -1:
            end = len(blocks)
        seg = []
        last = ""
        skip_left = 2
        for b in blocks[start + 1 : end]:
            t = b["text"]
            if any(k in t for k in self._STOP_KW):
                break
            if b["y"] > 0.86 * H:
                break
            if seg and re.search(r"[。！？]$", last) and not re.match(r"\d", t.strip()):
                # 可能是翻页后置顶重复的岗位标题
                if title_head and title_head in t and skip_left > 0:
                    skip_left -= 1
                    continue
                break
            seg.append(t)
            last = t
        return "".join(seg) if seg else "未识别到"

    def _extract_jd_req(self, blocks, H, job_title):
        ordered = sorted(blocks, key=lambda b: (b["src"], b["y"]))
        texts = [b["text"] for b in ordered]
        # JD 起始标题：多数岗位用「岗位职责」，但也有岗位用「岗位背景 /
        # 你会做什么 / 工作内容」描述 JD，这里按优先级取第一个出现在
        # 「任职要求」之前的 JD 标记，避免漏抓。
        jd_markers = ("岗位职责", "岗位背景", "你会做什么", "工作内容")
        i_jd = -1
        for kw in jd_markers:
            i = self._find_header(texts, kw)
            if i != -1 and (i_req_cached := self._find_header(texts, "任职要求")) != -1:
                if i < i_req_cached:
                    i_jd = i
                    break
            elif i != -1 and i_req_cached == -1:
                i_jd = i
                break
        i_req = self._find_header(texts, "任职要求")
        i_bonus = self._find_header(texts, "加分项")
        if i_bonus == -1:
            # 部分岗位用「加分」（非「加分项」）作边界
            i_bonus = self._find_first_containing(texts, "加分")
        title_head = job_title[:3] if job_title not in ("未识别到",) else ""

        if i_jd != -1 and i_req != -1 and i_req > i_jd:
            job_jd = self._cut_segment(ordered, i_jd, i_req, H, title_head)
        else:
            job_jd = "未识别到"

        if i_req != -1:
            # 任职要求 到 「加分项」或第一个停止信号 之间
            end = i_bonus if (i_bonus != -1 and i_bonus > i_req) else len(ordered)
            job_req = self._cut_segment(ordered, i_req, end, H, title_head)
        else:
            job_req = "未识别到"

        return job_jd, job_req


if __name__ == "__main__":
    import json
    import time

    # 通过环境变量 LOCAL_OCR_USE_GPU=1 开启 GPU 推理（默认 CPU）
    use_gpu = os.environ.get("LOCAL_OCR_USE_GPU", "0") == "1"

    # 基于脚本所在目录定位项目根，避免硬编码盘符在不同机器上失效
    _base = os.path.dirname(os.path.abspath(__file__))
    folders = [
        os.path.join(_base, "screenshots", "test"),
        os.path.join(_base, "screenshots", "test1"),
        os.path.join(_base, "screenshots", "test2"),
        os.path.join(_base, "screenshots", "test3"),
    ]
    eng = LocalOCREngine(use_gpu=use_gpu)

    # 模型初始化（含首次加载 PP-OCR 权重）计时
    t0 = time.time()
    eng._ensure_ocr()
    print(f"[init] 模型初始化耗时 {time.time() - t0:.1f}s")

    for folder in folders:
        imgs = sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        )
        t1 = time.time()
        info = eng.extract_job_info_from_screenshots(imgs)
        dt = time.time() - t1
        print(f"\n========== {folder} ({len(imgs)} 张) 耗时 {dt:.1f}s "
              f"({(dt / len(imgs)):.2f}s/张) ==========")
        print(json.dumps(info, ensure_ascii=False, indent=2))
