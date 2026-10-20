"""确定性文本规范化（第一档处理，不调用 LLM）。

只做可证明安全的操作：空白、中英混排空格、中文标点、术语大小写、用户替换。
不改写原意，不动数字与专有名词。
"""

from __future__ import annotations

import re
import unicodedata

CJK = "\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af"
_CJK_RE = re.compile(f"[{CJK}]")
_CJK_PUNCT = "，。！？；：、）】》”’…"
_OPEN_PUNCT = "（【《“‘"

# 中英混排术语的标准写法（只做大小写/空格规范化，不改变词义）
CANONICAL_TERMS: dict[str, str] = {
    "vs code": "VS Code",
    "visual studio code": "Visual Studio Code",
    "github": "GitHub",
    "gitlab": "GitLab",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "windows": "Windows",
    "linux": "Linux",
    "macos": "macOS",
    "openai": "OpenAI",
    "qwen": "Qwen",
    "llama": "llama.cpp",
    "agent": "Agent",
    "agents": "Agents",
    "memory": "Memory",
    "harness": "Harness",
    "session": "Session",
    "sessions": "Sessions",
    "prompt": "Prompt",
    "token": "Token",
    "tokens": "Tokens",
    "embedding": "Embedding",
    "llm": "LLM",
    "llms": "LLMs",
    "asr": "ASR",
    "tts": "TTS",
    "api": "API",
    "sdk": "SDK",
    "cpu": "CPU",
    "gpu": "GPU",
    "npu": "NPU",
    "ide": "IDE",
    "json": "JSON",
    "http": "HTTP",
    "https": "HTTPS",
    "sqlite": "SQLite",
    "powershell": "PowerShell",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "transformer": "Transformer",
    "rag": "RAG",
    "ui": "UI",
    "ux": "UX",
    "sdk": "SDK",
    "cli": "CLI",
    "cuda": "CUDA",
    "onnx": "ONNX",
    "wasapi": "WASAPI",
}

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*%?")
_URL_RE = re.compile(r"https?://[^\s，。！？；]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{1,}")


def _apply_replacements(text: str, replacements: dict[str, str] | None) -> str:
    if not replacements:
        return text
    for src, dst in sorted(replacements.items(), key=lambda kv: -len(str(kv[0]))):
        src, dst = str(src), str(dst)
        if not src or src == dst:
            continue
        flags = re.IGNORECASE if src.isascii() else 0
        text = re.sub(re.escape(src), dst, text, flags=flags)
    return text


def _apply_canonical(text: str, protected: set[str]) -> str:
    protected_lower = {p.lower() for p in protected}
    for term, canonical in sorted(CANONICAL_TERMS.items(), key=lambda kv: -len(kv[0])):
        if term.lower() in protected_lower or canonical.lower() in protected_lower:
            continue
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        text = re.sub(pattern, canonical, text, flags=re.IGNORECASE)
    return text


def normalize_text(
    text: str,
    *,
    replacements: dict[str, str] | None = None,
    protected_terms: tuple[str, ...] | list[str] = (),
    canonical_terms: bool = True,
    add_terminal: bool = True,
    convert_ascii_punct: bool = True,
) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    text = _apply_replacements(text, replacements)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", " ", text)
    text = text.strip()

    if canonical_terms:
        text = _apply_canonical(text, set(protected_terms))

    # 中文与拉丁字母之间补一个空格（不动数字，避免「第 3 章」过度处理）
    text = re.sub(rf"([{CJK}])([A-Za-z])", r"\1 \2", text)
    text = re.sub(rf"([A-Za-z])([{CJK}])", r"\1 \2", text)

    # 中文标点两侧不留空格
    text = re.sub(rf"\s*([{_CJK_PUNCT}])\s*", r"\1", text)
    text = re.sub(rf"\s*([{_OPEN_PUNCT}])\s*", r"\1", text)

    if convert_ascii_punct:
        # 中文语境下的半角标点转全角；数字小数点、URL 不受影响
        text = re.sub(rf"(?<=[{CJK}])\s*,\s*", "，", text)
        text = re.sub(rf"(?<=[{CJK}])\s*;\s*", "；", text)
        text = re.sub(rf"(?<=[{CJK}])\s*:\s*", "：", text)
        text = re.sub(rf"(?<=[{CJK}])\s*\?\s*", "？", text)
        text = re.sub(rf"(?<=[{CJK}])\s*!\s*", "！", text)
        text = re.sub(rf"(?<=[{CJK}])\.(?=[{CJK}]|$)", "。", text)

    # 重复标点折叠，但保留省略号
    text = re.sub(r"([，。！？；：、])\1+", r"\1", text)
    text = re.sub(r"，{2,}", "，", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text)
    text = re.sub(r"([，。！？；：、])\s+", r"\1", text)
    text = re.sub(r" {2,}", " ", text).strip()

    if add_terminal and _CJK_RE.search(text):
        text = _ensure_terminal(text)
    return text


def _ensure_terminal(text: str) -> str:
    if not text:
        return text
    closing = "”’）】》」』"
    i = len(text) - 1
    while i >= 0 and text[i] in closing:
        i -= 1
    if i < 0:
        return text
    last = text[i]
    if last in "。！？…；.!?":
        return text
    if last in "，、：,:;":
        return text[:i] + "。" + text[i + 1 :]
    return text[: i + 1] + "。" + text[i + 1 :]


def split_sentences(text: str) -> list[str]:
    """按中英文句末标点切句，保留标点。"""
    if not text:
        return []
    parts = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
    return [p.strip() for p in parts if p.strip()]


def numbers_in(text: str) -> list[str]:
    return _NUMBER_RE.findall(text or "")


def urls_in(text: str) -> list[str]:
    return _URL_RE.findall(text or "")


def emails_in(text: str) -> list[str]:
    return _EMAIL_RE.findall(text or "")


def ascii_words(text: str) -> list[str]:
    return _ASCII_WORD_RE.findall(text or "")


def strip_for_compare(text: str) -> str:
    """去掉标点/空格并统一大小写，用于相似度比较。"""
    text = re.sub(rf"[{_CJK_PUNCT}{_OPEN_PUNCT}.!?,;:\"'()\[\]{{}}]", "", text or "")
    text = re.sub(r"\s+", "", text)
    return text.lower()
