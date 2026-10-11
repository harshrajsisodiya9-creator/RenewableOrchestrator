import { useState } from "react";
import { createEvent, deleteEvent } from "../api";

const EVENT_TYPES = [
  "storm",
  "cloud",
  "wind_lull",
  "demand_spike",
  "price_spike",
  "maintenance",
];

export default function EventPanel({ projectId, events, onEventChange, currentTick }) {
  const [type, setType] = useState("storm");
  const [startTime, setStartTime] = useState("12:00");
  const [endTime, setEndTime] = useState("14:00");
  const [visibility, setVisibility] = useState("alerted");
  const [alertTime, setAlertTime] = useState("11:00");
  const [windSpeed, setWindSpeed] = useState("28");
  const [lineDerate, setLineDerate] = useState("100");
  const [pctDrop, setPctDrop] = useState("50");
  const [extraMw, setExtraMw] = useState("30");
  const [multiplier, setMultiplier] = useState("2.0");
  const [targets, setTargets] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleCreate(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const data = {
        type,
        start_time: startTime,
        end_time: endTime,
        visibility,
        alert_time: visibility === "alerted" ? alertTime : null,
        targets: targets ? targets.split(",").map((s) => s.trim()) : [],
      };
      if (type === "storm") {
        data.wind_speed_ms = parseFloat(windSpeed);
        data.line_derate_mw = parseFloat(lineDerate);
      } else if (type === "cloud" || type === "wind_lull") {
        data.pct_drop = parseFloat(pctDrop);
      } else if (type === "demand_spike") {
        data.extra_mw = parseFloat(extraMw);
      } else if (type === "price_spike") {
        data.multiplier = parseFloat(multiplier);
      }
      await createEvent(projectId, data);
      onEventChange?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(eventId) {
    try {
      await deleteEvent(projectId, eventId);
      onEventChange?.();
    } catch (err) {
      alert(err.message);
    }
  }

  function hhmmToTick(hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    return h * 4 + Math.floor(m / 15);
  }

  return (
    <div className="panel-section">
      <h3>Events</h3>
      <form className="event-form" onSubmit={handleCreate}>
        <label>
          Type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>{t.replace("_", " ")}</option>
            ))}
          </select>
        </label>
        <div className="inline-row">
          <label>
            Start
            <input type="text" value={startTime} onChange={(e) => setStartTime(e.target.value)} placeholder="HH:MM" />
          </label>
          <label>
            End
            <input type="text" value={endTime} onChange={(e) => setEndTime(e.target.value)} placeholder="HH:MM" />
          </label>
        </div>
        <label>
          Visibility
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)}>
            <option value="alerted">Alerted</option>
            <option value="surprise">Surprise</option>
          </select>
        </label>
        {visibility === "alerted" && (
          <label>
            Alert time
            <input type="text" value={alertTime} onChange={(e) => setAlertTime(e.target.value)} placeholder="HH:MM" />
          </label>
        )}
        {(type === "maintenance" || type === "cloud" || type === "wind_lull") && (
          <label>
            Targets (comma-sep)
            <input type="text" value={targets} onChange={(e) => setTargets(e.target.value)} placeholder="S1, W2" />
          </label>
        )}
        {type === "storm" && (
          <div className="inline-row">
            <label>Wind m/s <input type="number" value={windSpeed} onChange={(e) => setWindSpeed(e.target.value)} /></label>
            <label>Line MW <input type="number" value={lineDerate} onChange={(e) => setLineDerate(e.target.value)} /></label>
          </div>
        )}
        {(type === "cloud" || type === "wind_lull") && (
          <label>Drop % <input type="number" value={pctDrop} onChange={(e) => setPctDrop(e.target.value)} /></label>
        )}
        {type === "demand_spike" && (
          <label>Extra MW <input type="number" value={extraMw} onChange={(e) => setExtraMw(e.target.value)} /></label>
        )}
        {type === "price_spike" && (
          <label>Multiplier <input type="number" step="0.1" value={multiplier} onChange={(e) => setMultiplier(e.target.value)} /></label>
        )}
        {error && <div className="field-error">{error}</div>}
        <button className="btn-submit" type="submit" disabled={submitting}>
          Add Event
        </button>
      </form>

      {events.length > 0 && (
        <div className="event-list">
          {events.map((ev) => {
            const started = currentTick >= hhmmToTick(ev.start_time);
            return (
              <div key={ev.id} className="event-item">
                <span className="event-type-tag" data-type={ev.type}>
                  {ev.type.replace("_", " ")}
                </span>
                <span>{ev.start_time}–{ev.end_time}</span>
                {ev.source === "preset" && <span className="badge badge-mode">preset</span>}
                {!started && (
                  <button className="btn-icon remove" onClick={() => handleDelete(ev.id)} title="Delete">
                    &times;
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
