import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchProjects, fetchProjectDetail, deleteProject } from "../api";

export default function ProjectTable({ refreshKey, onRefresh }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

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

  async function handleDelete(e, project) {
    e.stopPropagation();
    if (!confirm(`Delete project "${project.name}"? This cannot be undone.`))
      return;
    try {
      await deleteProject(project.id);
      onRefresh?.();
    } catch (err) {
      alert(err.message);
    }
  }

  function handleRowClick(project) {
    if (!project.is_complete) return;
    navigate(`/projects/${project.id}/simulate`, { state: { projectName: project.name } });
  }

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
              <th>Status</th>
              <th>Solar Farms</th>
              <th>Total Solar (MW)</th>
              <th>Wind Farms</th>
              <th>Total Wind (MW)</th>
              <th>Batteries</th>
              <th>Battery (MWh)</th>
              <th>Consumers</th>
              <th>Day Load (MW)</th>
              <th>Grid (MW)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr
                key={p.id}
                onClick={() => handleRowClick(p)}
                className={p.is_complete ? "row-clickable" : "row-incomplete"}
                title={
                  p.is_complete
                    ? "Click to simulate"
                    : p.incomplete_reasons?.join("; ") || "Incomplete"
                }
              >
                <td className="cell-name">{p.name}</td>
                <td>
                  {p.is_complete ? (
                    <span className="badge badge-ok">Ready</span>
                  ) : (
                    <span className="badge badge-warn">Incomplete</span>
                  )}
                </td>
                <td>{p.solar_farms.map((f) => f.id).join(", ") || "-"}</td>
                <td className="cell-num">{p.total_solar_mw}</td>
                <td>{p.wind_farms.map((f) => f.id).join(", ") || "-"}</td>
                <td className="cell-num">{p.total_wind_mw}</td>
                <td>{p.batteries.map((b) => b.id).join(", ") || "-"}</td>
                <td className="cell-num">{p.total_battery_capacity_mwh}</td>
                <td>
                  {p.consumers.length > 0
                    ? p.consumers.map((c) => c.id).join(", ")
                    : "-"}
                </td>
                <td className="cell-num">
                  {p.consumers.length > 0
                    ? p.consumers
                        .reduce((sum, c) => sum + c.day_load_mw, 0)
                        .toFixed(1)
                    : "-"}
                </td>
                <td className="cell-num">
                  {p.grids.length > 0
                    ? p.grids.map((g) => g.line_limit_mw).join(", ")
                    : "-"}
                </td>
                <td>
                  <button
                    className="btn-icon remove"
                    onClick={(e) => handleDelete(e, p)}
                    title="Delete project"
                  >
                    &times;
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
