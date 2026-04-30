import { useMemo, useRef, useState, useEffect } from "react";
import { useLanguage } from "./i18n/LanguageContext.jsx";
import LanguageSwitcher from "./components/LanguageSwitcher.jsx";

const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001";

const createSession = (defaultTitle) => ({
  id: crypto.randomUUID(),
  title: defaultTitle,
  defaultTitle,
  createdAt: new Date().toISOString(),
});

export default function App() {
  const { lang, t } = useLanguage();

  const initialSession = useMemo(
    () => createSession(t("defaultSessionTitle")),
    // We intentionally seed the very first session with whatever the
    // language was at first render. Subsequent language switches only
    // affect newly created sessions; existing sessions keep their
    // original default title (tracked on `session.defaultTitle`).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );
  const [sessions, setSessions] = useState([initialSession]);
  const [activeSessionId, setActiveSessionId] = useState(initialSession.id);
  const [messagesBySession, setMessagesBySession] = useState({
    [initialSession.id]: [],
  });
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const listRef = useRef(null);

  const activeMessages = messagesBySession[activeSessionId] || [];

  const toolLabel = (tool) => {
    const map = {
      tarot: t("toolTarot"),
      lenormand: t("toolLenormand"),
      liuyao: t("toolLiuyao"),
    };
    return map[tool] || tool;
  };

  const dateLocale = lang === "zh" ? "zh-CN" : "en-CA";

  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [activeMessages]);

  const handleNewSession = () => {
    const next = createSession(t("defaultSessionTitle"));
    setSessions((prev) => [next, ...prev]);
    setMessagesBySession((prev) => ({ ...prev, [next.id]: [] }));
    setActiveSessionId(next.id);
  };

  const updateSessionTitle = (sessionId, message) => {
    setSessions((prev) =>
      prev.map((session) =>
        session.id === sessionId && session.title === session.defaultTitle
          ? { ...session, title: message.slice(0, 12) }
          : session
      )
    );
  };

  const appendMessage = (sessionId, message) => {
    setMessagesBySession((prev) => ({
      ...prev,
      [sessionId]: [...(prev[sessionId] || []), message],
    }));
  };

  const sendMessage = async (forceDivination = false) => {
    // The divination button must produce a request even when the textarea
    // is empty; we seed a generic question in the active language so the
    // payload is never empty. The plain Send button still no-ops on empty
    // input.
    let content = input.trim();
    if (!content && forceDivination) {
      content = t("divinationDefaultPrompt");
    }
    if (!content || isSending) return;

    setInput("");
    updateSessionTitle(activeSessionId, content);
    appendMessage(activeSessionId, { role: "user", content });

    setIsSending(true);
    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: activeSessionId,
          message: content,
          force_divination: forceDivination,
        }),
      });

      if (!response.ok) {
        throw new Error(t("errorRequestFailed"));
      }

      const data = await response.json();
      appendMessage(activeSessionId, {
        role: "assistant",
        content: data.message,
        tool: data.tool,
        trace: data.trace,
        reading: data.reading,
      });
    } catch (error) {
      // Surface the real error to the devtools console so production
      // failures can still be diagnosed; the bubble shows a friendly
      // localized fallback to the user.
      console.error("Chat request failed:", error);
      appendMessage(activeSessionId, {
        role: "assistant",
        content: t("errorNetwork"),
      });
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-title">{t("brandTitle")}</span>
          <span className="brand-sub">{t("brandSub")}</span>
        </div>
        <LanguageSwitcher />
        <button className="primary-btn" onClick={handleNewSession}>
          {t("newSession")}
        </button>
        <div className="session-list">
          {sessions.map((session) => (
            <button
              key={session.id}
              className={
                session.id === activeSessionId ? "session-item active" : "session-item"
              }
              onClick={() => setActiveSessionId(session.id)}
            >
              <div className="session-title">{session.title}</div>
              <div className="session-time">
                {new Date(session.createdAt).toLocaleDateString(dateLocale)}
              </div>
            </button>
          ))}
        </div>
      </aside>

      <main className="chat-panel">
        <header className="chat-header">
          <div>
            <h1>{t("chatHeaderTitle")}</h1>
            <p>{t("chatHeaderSubtitle")}</p>
          </div>
          <div className="status-chip">{t("statusChip")}</div>
        </header>

        <section className="message-list" ref={listRef}>
          {activeMessages.length === 0 ? (
            <div className="empty-state">
              <h2>{t("emptyStateTitle")}</h2>
              <p>{t("emptyStateExample")}</p>
            </div>
          ) : (
            activeMessages.map((message, index) => (
              <article
                key={`${message.role}-${index}`}
                className={message.role === "assistant" ? "message assistant" : "message user"}
              >
                <div className="bubble">
                  <div className="meta">
                    {message.role === "assistant" ? t("bubbleAssistant") : t("bubbleUser")}
                  </div>
                  <div className="content">{message.content}</div>
                  {message.role === "assistant" && message.tool && message.tool !== "chat" && (
                    <details className="detail-card">
                      <summary>{t("detailToggle")}</summary>
                      <div className="detail-grid">
                        <div>
                          <h4>{t("detailToolHeading")}</h4>
                          <p>{toolLabel(message.tool)}</p>
                        </div>
                        {message.reading && (
                          <div>
                            <h4>{t("detailReadingHeading")}</h4>
                            <p>{message.reading.verdict}</p>
                          </div>
                        )}
                      </div>
                      {message.trace && (
                        <div className="trace-block">
                          <h4>{t("detailTraceHeading")}</h4>
                          <pre>{JSON.stringify(message.trace, null, 2)}</pre>
                        </div>
                      )}
                    </details>
                  )}
                </div>
              </article>
            ))
          )}
        </section>

        <section className="composer floating">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("composerPlaceholder")}
            rows={3}
          />
          <div className="composer-actions">
            <span className="hint">{t("composerHint")}</span>
            <div className="composer-buttons">
              <button className="ghost-btn" onClick={() => sendMessage(false)} disabled={isSending}>
                {t("composerSend")}
              </button>
              <button className="primary-btn" onClick={() => sendMessage(true)} disabled={isSending}>
                {t("composerDivination")}
              </button>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
