import re


def normalize_telegram_channel_name(raw: str) -> str:
    """Normalize channel usernames or t.me links into plain channel name."""
    text = (raw or "").strip()
    if not text:
        return ""

    text = text.lstrip("@").strip()
    lower = text.lower()
    if lower.startswith("https://t.me/") or lower.startswith("http://t.me/"):
        text = text.split("://", 1)[1]
    if text.lower().startswith("t.me/"):
        text = text.split("/", 1)[1]

    text = text.split("?", 1)[0].split("#", 1)[0].strip("/")
    if "/" in text:
        text = text.split("/", 1)[0]
    return text.lstrip("@").strip()


def clean_telegram_text(text: str, strip_links: bool = False) -> str:
    """清洗 Telegram 消息文本"""
    if not text:
        return ""

    # 1. 移除特定的频道签名
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if "频道" in line and "@" in line:
            continue
        if line.strip().startswith("@") and len(line) < 20:
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # 2. 正则内容清洗
    patterns = [
        r"[\*＊\-]?\s*此原图经过处理.*",
        r"投稿 by .*",
    ]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # 3. 去除粗体/斜体标记（可选保留，根据需求）
    text = text.replace("**", "").replace("__", "")

    # 4. 处理 Markdown 链接  ← 这里是重点修改
    if strip_links:
        # 只保留 [文本] 部分，丢弃 (链接)
        text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    else:
        # 原有行为：显示 文本: 链接
        text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1: \2", text)

    return text.strip()
