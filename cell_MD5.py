# 示例代码仅供参考，请勿在生产环境中直接使用
import hashlib
def calculate_md5(file_path):
    """计算文档的 MD5 值。

    Args:
        file_path (str): 文档的路径。

    Returns:
        str: 文档的 MD5 值。
    """
    md5_hash = hashlib.md5()

    # 以二进制形式读取文件
    with open(file_path, "rb") as f:
        # 按块读取文件，避免大文件占用过多内存
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)

    return md5_hash.hexdigest()

# 使用示例
file_path = "C:/Users/90653/Desktop/临时/Screenshot_2026-07-07-11-08-30-848_com.hpbr.bosszhipin.jpg"
md5_value = calculate_md5(file_path)
print(f"文档的MD5值为: {md5_value}")