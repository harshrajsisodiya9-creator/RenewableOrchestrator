import { useState } from "react";
import { injectFault } from "../api";

export default function InjectPanel({ project }) {
  const [assetType, setAssetType] = useState("solar");
  const [assetId, setAssetId] = useState("");
  const [action, setAction] = useState("trip");
  const [duration, setDuration] = useState("8");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const assetOptions = {
    solar: (project?.solar_farms || []).map((f) => f.id),
    wind: (project?.wind_farms || []).map((f) => f.id),
    battery: (project?.batteries || []).map((b) => b.id),
  };

  const ids = assetOptions[assetType] || [];

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setResult(null);
    if (!assetId) {
      setError("Select an asset");
      return;
    }
    try {
      const r = await injectFault({
        asset_type: assetType,
        asset_id: assetId,
        action,
        duration_ticks: action === "trip" ? Number(duration) || null : null,
        project_name: project.name,
      });
      setResult(r);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="panel-section">
      <h3>Fault Injection</h3>
      <form className="inject-form" onSubmit={handleSubmit}>
        <label>
          Asset type
          <select
            value={assetType}
            onChange={(e) => {
              setAssetType(e.target.value);
              setAssetId("");
            }}
          >
            <option value="solar">Solar</option>
            <option value="wind">Wind</option>
            <option value="battery">Battery</option>
          </select>
        </label>
        <label>
          Asset ID
          <select value={assetId} onChange={(e) => setAssetId(e.target.value)}>
            <option value="">—</option>
            {ids.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Action
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="trip">Trip</option>
            <option value="restore">Restore</option>
          </select>
        </label>
        {action === "trip" && (
          <label>
            Duration (ticks)
            <input
              type="number"
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
              placeholder="auto-restore after N ticks"
            />
          </label>
        )}
        {error && <div className="field-error">{error}</div>}
        <button className="btn-submit" type="submit">
          Inject
        </button>
      </form>
      {result && (
        <div className="inject-result">
          <span className={`badge ${result.status === "tripped" ? "badge-warn" : "badge-ok"}`}>
            {result.asset_id}: {result.status}
          </span>
          <p className="sup-reason">{result.message}</p>
        </div>
      )}
    </div>
  );
}
