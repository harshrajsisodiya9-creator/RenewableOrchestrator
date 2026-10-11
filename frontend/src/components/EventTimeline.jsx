const TYPE_COLORS = {
  storm: "var(--red)",
  cloud: "#9ca3af",
  maintenance: "#ea580c",
  demand_spike: "#eab308",
  price_spike: "#7c3aed",
  wind_lull: "#64748b",
};

function hhmmToTick(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 4 + Math.floor(m / 15);
}

export default function EventTimeline({ events, currentTick }) {
  return (
    <div className="chart-card">
      <h3>Event Timeline</h3>
      <div className="event-timeline">
        <div className="timeline-axis">
          {[0, 6, 12, 18, 24].map((h) => (
            <span
              key={h}
              className="axis-label"
              style={{ left: `${(h / 24) * 100}%` }}
            >
              {String(h).padStart(2, "0")}:00
            </span>
          ))}
        </div>
        <div className="timeline-bars">
          {events.map((ev) => {
            const start = hhmmToTick(ev.start_time);
            const end = hhmmToTick(ev.end_time);
            const left = (start / 96) * 100;
            const width = Math.max(((end - start) / 96) * 100, 0.5);
            return (
              <div
                key={ev.id}
                className="event-bar"
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  backgroundColor: TYPE_COLORS[ev.type] || "#9ca3af",
                }}
                title={`${ev.type} ${ev.start_time}–${ev.end_time}${ev.visibility === "surprise" ? " (surprise)" : ""}`}
              >
                <span className="event-bar-label">{ev.type}</span>
              </div>
            );
          })}
          {currentTick >= 0 && (
            <div
              className="tick-marker"
              style={{ left: `${(currentTick / 96) * 100}%` }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
