from __future__ import annotations

from typing import Any, Dict, List


LOVE_KEYWORDS = [
    "感情",
    "爱情",
    "恋爱",
    "喜欢",
    "暧昧",
    "分手",
    "复合",
    "对象",
    "男友",
    "女友",
    "相亲",
    "婚姻",
    "结婚",
    "关系",
    "情感",
    "TA",
]
CAREER_KEYWORDS = [
    "工作",
    "职业",
    "事业",
    "升职",
    "跳槽",
    "面试",
    "offer",
    "薪资",
    "薪水",
    "裁员",
    "同事",
    "岗位",
    "转正",
    "考试",
    "学习",
    "成绩",
]
GENTLE_MARKERS = ["请", "希望", "麻烦", "能不能", "可以吗", "想", "温柔", "安慰", "求助"]
DIRECT_MARKERS = ["直接", "快点", "说实话", "结论", "结果", "是或否", "只要结果", "别绕"]
CAREER_ROUTE_HINTS = ["面试", "offer", "升职", "裁员", "跳槽", "绩效", "简历", "考试", "学习"]
DIVINATION_KEYWORDS = ["占卜", "抽牌", "塔罗", "六爻", "雷诺曼", "算一算", "看运势", "问卜", "测一测"]
DIVINATION_KEYWORDS_EN = [
    "divination",
    "tarot",
    "lenormand",
    "oracle",
    "fortune",
    "draw a card",
    "draw card",
    "card reading",
    "i ching",
    "i-ching",
    "iching",
    "liuyao",
]


def parse_question(question: str) -> Dict[str, Any]:
    cleaned = (question or "").strip()
    domain = "general"
    if _contains_any(cleaned, LOVE_KEYWORDS):
        domain = "love"
    elif _contains_any(cleaned, CAREER_KEYWORDS):
        domain = "career"

    tone = "gentle" if _contains_any(cleaned, GENTLE_MARKERS) else "direct"
    if _contains_any(cleaned, DIRECT_MARKERS):
        tone = "direct"

    need_clarification = len(cleaned) < 3

    return {
        "domain": domain,
        "tone": tone,
        "need_clarification": need_clarification,
    }


def detect_intent(question: str) -> str:
    if _contains_any(question, DIVINATION_KEYWORDS):
        return "divination"
    if _contains_any((question or "").lower(), DIVINATION_KEYWORDS_EN):
        return "divination"
    return "chat"


def rule_route(question: str, domain: str, tone: str) -> str:
    if domain == "career" or _contains_any(question, CAREER_ROUTE_HINTS):
        return "liuyao"
    if domain == "love" and tone == "gentle":
        return "tarot"
    if domain == "love" and tone == "direct":
        return "lenormand"
    return "tarot" if tone == "gentle" else "lenormand"


def fallback_narration(
    tool: str,
    verdict: str,
    advice: List[str] | str,
    tone: str,
    need_clarification: bool,
    lang: str = "zh",
) -> str:
    if lang == "en":
        tool_label = {
            "tarot": "Tarot",
            "lenormand": "Lenormand",
            "liuyao": "I-Ching (Liuyao)",
        }.get(tool, tool)
        advice_text = "; ".join(advice) if isinstance(advice, list) else str(advice)
        if need_clarification:
            return (
                f"I need a bit more context to give a meaningful {tool_label} reading. "
                "Please share the key background or a specific time frame."
            )
        if tone == "gentle":
            return (
                f"From the {tool_label} reading: {verdict} "
                f"Suggestion: {advice_text}."
            )
        return f"{tool_label} reading: {verdict} Suggestion: {advice_text}."

    tool_cn = {
        "tarot": "塔罗",
        "lenormand": "雷诺曼",
        "liuyao": "六爻",
    }.get(tool, tool)

    advice_text = "；".join(advice) if isinstance(advice, list) else str(advice)

    if need_clarification:
        return (
            f"我需要更多信息来进行{tool_cn}占问，"
            "请补充关键背景或具体时间范围。"
        )
    if tone == "gentle":
        return (
            f"从{tool_cn}的结果看：{verdict}。"
            f"建议：{advice_text}。"
        )
    return f"{tool_cn}解读：{verdict}。建议：{advice_text}。"


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)
