import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import translations, {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
} from "./translations.js";

const STORAGE_KEY = "oracle.lang";

const LanguageContext = createContext(null);

const isSupported = (lang) => SUPPORTED_LANGUAGES.includes(lang);

const readStoredLanguage = () => {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isSupported(stored) ? stored : null;
  } catch {
    return null;
  }
};

const detectBrowserLanguage = () => {
  if (typeof navigator === "undefined") return DEFAULT_LANGUAGE;
  const raw = (navigator.language || "").toLowerCase();
  if (raw.startsWith("zh")) return "zh";
  if (raw.startsWith("en")) return "en";
  return DEFAULT_LANGUAGE;
};

const resolveInitialLanguage = () =>
  readStoredLanguage() || detectBrowserLanguage();

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(resolveInitialLanguage);

  useEffect(() => {
    if (typeof document !== "undefined") {
      if (document.documentElement) {
        document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
      }
      const titleSource = translations[lang] || {};
      const fallbackSource = translations[DEFAULT_LANGUAGE] || {};
      const nextTitle = titleSource.pageTitle || fallbackSource.pageTitle;
      if (nextTitle) {
        document.title = nextTitle;
      }
    }
    if (typeof window !== "undefined") {
      try {
        window.localStorage.setItem(STORAGE_KEY, lang);
      } catch {
        // localStorage may be unavailable (private mode, etc.); ignore.
      }
    }
  }, [lang]);

  const setLang = useCallback((next) => {
    if (!isSupported(next)) return;
    setLangState(next);
  }, []);

  const t = useCallback(
    (key, fallback) => {
      const active = translations[lang] || {};
      const source = translations[DEFAULT_LANGUAGE] || {};
      if (key in active) return active[key];
      if (key in source) return source[key];
      return fallback ?? key;
    },
    [lang]
  );

  const value = useMemo(
    () => ({ lang, setLang, t }),
    [lang, setLang, t]
  );

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return ctx;
}
