import { useState } from "react";
import {
  createProject,
  createSolarFarm,
  createWindFarm,
  createBattery,
  createGrid,
} from "../api";

const emptySolar = () => ({ id: "", power_output_mw: "" });
const emptyWind = () => ({ id: "", power_output_mw: "" });
const emptyBattery = () => ({
  id: "",
  total_capacity_mw: "",
  charge_discharge_rate_mwh: "",
});

export default function ProjectForm({ onCreated }) {
  const [name, setName] = useState("");
  const [solarFarms, setSolarFarms] = useState([emptySolar()]);
  const [windFarms, setWindFarms] = useState([emptyWind()]);
  const [batteries, setBatteries] = useState([emptyBattery()]);
  const [grid, setGrid] = useState({
    line_limit_mw: "",
    buy_premium_per_kwh: "",
    price_cap_per_kwh: "",
    emission_tco2_per_mwh: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  function updateList(list, setList, idx, field, value) {
    const copy = [...list];
    copy[idx] = { ...copy[idx], [field]: value };
    setList(copy);
  }

  function removeFromList(list, setList, idx) {
    if (list.length <= 1) return;
    setList(list.filter((_, i) => i !== idx));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await createProject(name);

      for (const sf of solarFarms) {
        if (!sf.id || !sf.power_output_mw) continue;
        await createSolarFarm({
          id: sf.id,
          power_output_mw: Number(sf.power_output_mw),
          project_name: name,
        });
      }

      for (const wf of windFarms) {
        if (!wf.id || !wf.power_output_mw) continue;
        await createWindFarm({
          id: wf.id,
          power_output_mw: Number(wf.power_output_mw),
          project_name: name,
        });
      }

      for (const bat of batteries) {
        if (!bat.id || !bat.total_capacity_mw) continue;
        await createBattery({
          id: bat.id,
          total_capacity_mw: Number(bat.total_capacity_mw),
          charge_discharge_rate_mwh: Number(bat.charge_discharge_rate_mwh),
          project_name: name,
        });
      }

      if (grid.line_limit_mw) {
        await createGrid({
          line_limit_mw: Number(grid.line_limit_mw),
          buy_premium_per_kwh: Number(grid.buy_premium_per_kwh) || 0,
          price_cap_per_kwh: Number(grid.price_cap_per_kwh) || 0,
          emission_tco2_per_mwh: Number(grid.emission_tco2_per_mwh) || 0,
          project_name: name,
        });
      }

      setName("");
      setSolarFarms([emptySolar()]);
      setWindFarms([emptyWind()]);
      setBatteries([emptyBattery()]);
      setGrid({
        line_limit_mw: "",
        buy_premium_per_kwh: "",
        price_cap_per_kwh: "",
        emission_tco2_per_mwh: "",
      });
      onCreated();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="project-form" onSubmit={handleSubmit}>
      <h2>Add New Project</h2>

      {error && <div className="form-error">{error}</div>}

      <label>
        Project Name
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="e.g. farm 1"
        />
      </label>

      {/* Solar Farms */}
      <fieldset>
        <legend>Solar Farms</legend>
        {solarFarms.map((sf, i) => (
          <div key={i} className="inline-row">
            <input
              type="text"
              placeholder="ID (S1)"
              value={sf.id}
              onChange={(e) =>
                updateList(solarFarms, setSolarFarms, i, "id", e.target.value)
              }
            />
            <input
              type="number"
              placeholder="MW"
              value={sf.power_output_mw}
              onChange={(e) =>
                updateList(
                  solarFarms,
                  setSolarFarms,
                  i,
                  "power_output_mw",
                  e.target.value
                )
              }
            />
            <button
              type="button"
              className="btn-icon remove"
              onClick={() => removeFromList(solarFarms, setSolarFarms, i)}
              title="Remove"
            >
              &times;
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn-add"
          onClick={() => setSolarFarms([...solarFarms, emptySolar()])}
        >
          + Add Solar Farm
        </button>
      </fieldset>

      {/* Wind Farms */}
      <fieldset>
        <legend>Wind Farms</legend>
        {windFarms.map((wf, i) => (
          <div key={i} className="inline-row">
            <input
              type="text"
              placeholder="ID (W1)"
              value={wf.id}
              onChange={(e) =>
                updateList(windFarms, setWindFarms, i, "id", e.target.value)
              }
            />
            <input
              type="number"
              placeholder="MW"
              value={wf.power_output_mw}
              onChange={(e) =>
                updateList(
                  windFarms,
                  setWindFarms,
                  i,
                  "power_output_mw",
                  e.target.value
                )
              }
            />
            <button
              type="button"
              className="btn-icon remove"
              onClick={() => removeFromList(windFarms, setWindFarms, i)}
              title="Remove"
            >
              &times;
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn-add"
          onClick={() => setWindFarms([...windFarms, emptyWind()])}
        >
          + Add Wind Farm
        </button>
      </fieldset>

      {/* Batteries */}
      <fieldset>
        <legend>Batteries</legend>
        {batteries.map((bat, i) => (
          <div key={i} className="inline-row three-col">
            <input
              type="text"
              placeholder="ID (B1)"
              value={bat.id}
              onChange={(e) =>
                updateList(batteries, setBatteries, i, "id", e.target.value)
              }
            />
            <input
              type="number"
              placeholder="Capacity MW"
              value={bat.total_capacity_mw}
              onChange={(e) =>
                updateList(
                  batteries,
                  setBatteries,
                  i,
                  "total_capacity_mw",
                  e.target.value
                )
              }
            />
            <input
              type="number"
              placeholder="Rate MWh"
              value={bat.charge_discharge_rate_mwh}
              onChange={(e) =>
                updateList(
                  batteries,
                  setBatteries,
                  i,
                  "charge_discharge_rate_mwh",
                  e.target.value
                )
              }
            />
            <button
              type="button"
              className="btn-icon remove"
              onClick={() => removeFromList(batteries, setBatteries, i)}
              title="Remove"
            >
              &times;
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn-add"
          onClick={() => setBatteries([...batteries, emptyBattery()])}
        >
          + Add Battery
        </button>
      </fieldset>

      {/* Grid */}
      <fieldset>
        <legend>Transmission Grid</legend>
        <div className="grid-fields">
          <label>
            Line Limit (MW)
            <input
              type="number"
              value={grid.line_limit_mw}
              onChange={(e) =>
                setGrid({ ...grid, line_limit_mw: e.target.value })
              }
              placeholder="150"
            />
          </label>
          <label>
            Buy Premium (/kWh)
            <input
              type="number"
              step="0.01"
              value={grid.buy_premium_per_kwh}
              onChange={(e) =>
                setGrid({ ...grid, buy_premium_per_kwh: e.target.value })
              }
              placeholder="0.50"
            />
          </label>
          <label>
            Price Cap (/kWh)
            <input
              type="number"
              step="0.01"
              value={grid.price_cap_per_kwh}
              onChange={(e) =>
                setGrid({ ...grid, price_cap_per_kwh: e.target.value })
              }
              placeholder="10.0"
            />
          </label>
          <label>
            Emission (tCO2/MWh)
            <input
              type="number"
              step="0.01"
              value={grid.emission_tco2_per_mwh}
              onChange={(e) =>
                setGrid({ ...grid, emission_tco2_per_mwh: e.target.value })
              }
              placeholder="0.71"
            />
          </label>
        </div>
      </fieldset>

      <button type="submit" className="btn-submit" disabled={submitting}>
        {submitting ? "Creating..." : "Create Project"}
      </button>
    </form>
  );
}
