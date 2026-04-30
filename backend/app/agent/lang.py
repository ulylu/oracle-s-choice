"""Lightweight, dependency-free language detection.

Used by the agent to decide what language the assistant should reply in.
Only two outputs are supported: ``"zh"`` and ``"en"``. The rule is
deterministic and biased toward Chinese for empty / ambiguous input so
that the original Chinese-first project behavior is preserved.
"""
from __future__ import annotations


def detect_language(text: str) -> str:
    """Return ``"zh"`` or ``"en"`` based on character dominance.

    Rules (deterministic, no external deps):

    * Count CJK Unified Ideographs (U+4E00 - U+9FFF) → ``cjk``.
    * Count ASCII Latin letters (A-Z, a-z) → ``latin``.
    * CJK characters are weighted 3x because each one carries roughly
      as much information as a short English word (~3 letters).
      Without weighting, a Chinese phrase mixed with a few English
      words would be pulled toward English by raw character count.
    * If ``cjk * 3 >= latin`` → ``"zh"``. Ties and empty / punctuation
      only input therefore default to Chinese, preserving the original
      project behavior.
    * Otherwise → ``"en"``.

    Examples:
        >>> detect_language("我最近很累")
        'zh'
        >>> detect_language("I've been feeling tired lately.")
        'en'
        >>> detect_language("我感觉很 anxious about my interview")
        'en'
        >>> detect_language("今天面试 hello")
        'zh'
        >>> detect_language("")
        'zh'
    """
    if not text:
        return "zh"

    cjk = 0
    latin = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            cjk += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1

    if cjk * 3 >= latin:
        return "zh"
    return "en"
