// Bilingual dictionary for Oracle's Choice.
//
// Keep keys stable and descriptive. When adding a new string to the UI,
// add it to BOTH `zh` and `en` here, then reference it via `t("key")`
// from useLanguage().
//
// Conventions:
// - `zh` is the source-of-truth language (the original project language).
// - If a key is missing in `en`, the LanguageContext will fall back to `zh`.
// - Values may be functions for strings that need runtime arguments,
//   e.g. errorWithCode: (code) => `Error ${code}`.

export const SUPPORTED_LANGUAGES = ["zh", "en"];

export const DEFAULT_LANGUAGE = "zh";

export const LANGUAGE_LABELS = {
  zh: "中文",
  en: "English",
};

const translations = {
  zh: {
    // Document / browser tab
    pageTitle: "问象 | Oracle's Choice",

    // Brand / sidebar
    brandTitle: "问象",
    brandSub: "Oracle's Choice",
    newSession: "新建会话",
    defaultSessionTitle: "新的会话",

    // Chat header
    chatHeaderTitle: "占问对话",
    chatHeaderSubtitle: "输入你的问题，系统将自动选择合适的占卜方式。",
    statusChip: "在线 · SpoonOS Graph Agent",

    // Empty state
    emptyStateTitle: "从一个问题开始",
    emptyStateExample: "例如：\u201C这段感情还有机会吗？\u201D",

    // Message bubble
    bubbleAssistant: "问象",
    bubbleUser: "我",

    // Detail / trace card
    detailToggle: "展开解读细节",
    detailToolHeading: "使用的占卜工具",
    detailReadingHeading: "结构化结果",
    detailTraceHeading: "Agent 决策过程",

    // Divination tool labels
    toolTarot: "塔罗",
    toolLenormand: "雷诺曼",
    toolLiuyao: "六爻",

    // Composer
    composerPlaceholder: "写下你的问题，按 Enter 发送",
    composerHint: "Shift + Enter 换行",
    composerSend: "发送",
    composerDivination: "占卜",

    // Errors
    errorRequestFailed: "请求失败，请稍后再试",
    errorNetwork: "网络暂时不稳定，请稍后再试。",

    // Language switcher (a11y)
    languageSwitcherLabel: "切换语言",
  },

  en: {
    pageTitle: "Oracle's Choice | 问象",

    brandTitle: "Oracle's Choice",
    brandSub: "问象",
    newSession: "New chat",
    defaultSessionTitle: "New chat",

    chatHeaderTitle: "Ask the Oracle",
    chatHeaderSubtitle:
      "Type your question and the system will pick the right divination method.",
    statusChip: "Online · SpoonOS Graph Agent",

    emptyStateTitle: "Start with a question",
    emptyStateExample: "For example: \u201CIs there still hope for this relationship?\u201D",

    bubbleAssistant: "Oracle",
    bubbleUser: "You",

    detailToggle: "Show reading details",
    detailToolHeading: "Divination tool used",
    detailReadingHeading: "Structured result",
    detailTraceHeading: "Agent decision trace",

    toolTarot: "Tarot",
    toolLenormand: "Lenormand",
    toolLiuyao: "I-Ching (Liuyao)",

    composerPlaceholder: "Write your question and press Enter to send",
    composerHint: "Shift + Enter for a new line",
    composerSend: "Send",
    composerDivination: "Divination",

    errorRequestFailed: "Request failed, please try again later.",
    errorNetwork: "The network is a bit unstable. Please try again in a moment.",

    languageSwitcherLabel: "Switch language",
  },
};

export default translations;
