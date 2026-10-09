import { useEffect, useState } from "react";
import { fetchProjects, fetchProjectDetail } from "../api";

export default function ProjectTable({ refreshKey }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const list = await fetchProjects();
        const details = await Promise.all(
          list.map((p) => fetchProjectDetail(p.name))
        );
        if (!cancelled) setProjects(details);
      } catch {
        if (!cancelled) setProjects([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (loading) {
    return (
      <div className="table-container">
        <h2>Existing Projects</h2>
        <p className="table-loading">Loading...</p>
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="table-container">
        <h2>Existing Projects</h2>
        <p className="table-empty">No projects yet. Create one to get started.</p>
      </div>
    );
  }

  return (
    <div className="table-container">
      <h2>Existing Projects</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Project</th>
              <th>Solar Farms</th>
              <th>Total Solar (MW)</th>
              <th>Wind Farms</th>
              <th>Total Wind (MW)</th>
              <th>Batteries</th>
              <th>Battery Capacity (MW)</th>
              <th>Grid Limit (MW)</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td className="cell-name">{p.name}</td>
                <td>{p.solar_farms.map((f) => f.id).join(", ") || "-"}</td>
                <td className="cell-num">{p.total_solar_mw}</td>
                <td>{p.wind_farms.map((f) => f.id).join(", ") || "-"}</td>
                <td className="cell-num">{p.total_wind_mw}</td>
                <td>{p.batteries.map((b) => b.id).join(", ") || "-"}</td>
                <td className="cell-num">{p.total_battery_capacity_mw}</td>
                <td className="cell-num">
                  {p.grids.length > 0
                    ? p.grids.map((g) => g.line_limit_mw).join(", ")
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
