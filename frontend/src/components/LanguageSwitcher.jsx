import { useLanguage } from "../i18n/LanguageContext.jsx";
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES } from "../i18n/translations.js";

export default function LanguageSwitcher() {
  const { lang, setLang, t } = useLanguage();

  return (
    <div
      className="language-switcher"
      role="group"
      aria-label={t("languageSwitcherLabel")}
    >
      {SUPPORTED_LANGUAGES.map((code) => {
        const isActive = code === lang;
        return (
          <button
            key={code}
            type="button"
            className={
              isActive
                ? "language-switcher-btn active"
                : "language-switcher-btn"
            }
            aria-pressed={isActive}
            onClick={() => setLang(code)}
          >
            {LANGUAGE_LABELS[code]}
          </button>
        );
      })}
    </div>
  );
}
