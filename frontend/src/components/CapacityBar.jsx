export default function CapacityBar({ project }) {
  if (!project) return null;

  const totalSolar = project.total_solar_mw || 0;
  const totalWind = project.total_wind_mw || 0;
  const batteryRate = (project.batteries || []).reduce(
    (sum, b) => sum + (b.max_rate_mw || 0),
    0
  );
  const batteryCapacity = project.total_battery_capacity_mwh || 0;
  const gridLimit =
    (project.grids || []).reduce((sum, g) => sum + (g.line_limit_mw || 0), 0);

  return (
    <div className="capacity-bar">
      <h3 className="cap-heading">Max Capacity</h3>
      <div className="cap-item">
        <span className="cap-dot cap-solar" />
        <span className="cap-label">Solar</span>
        <span className="cap-value">{totalSolar} MW</span>
      </div>
      <div className="cap-item">
        <span className="cap-dot cap-wind" />
        <span className="cap-label">Wind</span>
        <span className="cap-value">{totalWind} MW</span>
      </div>
      <div className="cap-item">
        <span className="cap-dot cap-battery" />
        <span className="cap-label">Battery</span>
        <span className="cap-value">
          {batteryCapacity} MWh / {batteryRate} MW
        </span>
      </div>
      <div className="cap-item">
        <span className="cap-dot cap-grid" />
        <span className="cap-label">Grid</span>
        <span className="cap-value">{gridLimit} MW</span>
      </div>
    </div>
  );
}
