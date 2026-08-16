"""
诊断脚本：用 PaddleOCR 跑指定截图，把每个文字块的
text / x / y / w / h / score / 所属截图序号  dump 成 JSON，
方便人工校准"布局 -> 字段"的提取规则。

用法：
    python ocr_diagnose.py <文件夹或图片1> [图片2 ...]
"""

import os
import sys
import json

# 把脚本所在目录加入 path，便于直接 import 本模块的引擎
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from local_ocr_engine import LocalOCREngine


def collect_images(paths):
    imgs = []
    for p in paths:
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    imgs.append(os.path.join(p, f))
        elif os.path.isfile(p):
            imgs.append(p)
    return imgs


def main():
    if len(sys.argv) < 2:
        print("用法: python ocr_diagnose.py <文件夹或图片> [...]")
        sys.exit(1)

    imgs = collect_images(sys.argv[1:])
    print(f"共 {len(imgs)} 张图片")

    eng = LocalOCREngine()
    dump = {}
    for idx, img in enumerate(imgs):
        blocks = eng.ocr_image(img)
        dump[os.path.basename(img)] = [
            {
                "text": b["text"],
                "x": round(b["x"]),
                "y": round(b["y"]),
                "w": round(b["w"]),
                "h": round(b["h"]),
                "score": round(b["score"], 2),
            }
            for b in blocks
        ]
        print(f"\n[{idx}] {os.path.basename(img)}  -> {len(blocks)} 块")

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_blocks_dump.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)
    print(f"\n已 dump 到: {out_path}")


if __name__ == "__main__":
    main()
