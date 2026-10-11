import { useEffect, useRef } from "react";

const RISK_CLASS = {
  low: "risk-low",
  medium: "risk-medium",
  high: "risk-high",
  critical: "risk-critical",
};

export default function SupervisorFeed({ ticks }) {
  const feedRef = useRef(null);

  useEffect(() => {
    const el = feedRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [ticks.length]);

  const entries = ticks.filter((t, i) => {
    if (!t.supervisor || !t.supervisor.risk_level) return false;
    if (t.supervisor.called !== undefined) return t.supervisor.called;
    const prev = ticks[i - 1]?.supervisor;
    return (
      !prev ||
      prev.strategy_reason !== t.supervisor.strategy_reason ||
      prev.risk_level !== t.supervisor.risk_level
    );
  });

  if (entries.length === 0) {
    return (
      <div className="panel-section">
        <h3>Decisions Made</h3>
        <p className="table-empty">No decisions yet.</p>
      </div>
    );
  }

  return (
    <div className="panel-section">
      <h3>Decisions Made</h3>
      <div className="supervisor-feed" ref={feedRef}>
        {entries.map((t) => (
          <div
            key={t.tick}
            className={`sup-entry ${RISK_CLASS[t.supervisor.risk_level] || ""}`}
          >
            <div className="sup-header">
              <span className="sup-tick">{t.timestamp}</span>
              <span className={`badge badge-${t.supervisor.risk_level}`}>
                {t.supervisor.risk_level}
              </span>
              {t.supervisor.plan_status === "fallback" && (
                <span className="badge badge-warn">fallback</span>
              )}
            </div>
            <p className="sup-reason">{t.supervisor.strategy_reason}</p>
            {t.supervisor.monitor_triggers?.length > 0 && (
              <div className="sup-triggers">
                {t.supervisor.monitor_triggers.map((tr, i) => (
                  <span key={i} className="trigger-tag">
                    {tr}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
