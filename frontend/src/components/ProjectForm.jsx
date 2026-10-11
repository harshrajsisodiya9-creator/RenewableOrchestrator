import { useState, useCallback } from "react";
import { createProjectFull } from "../api";

function nextId(prefix, list) {
  const nums = list
    .map((r) => r.id)
    .filter((id) => id.startsWith(prefix))
    .map((id) => parseInt(id.slice(prefix.length), 10))
    .filter((n) => !isNaN(n));
  const max = nums.length ? Math.max(...nums) : 0;
  return `${prefix}${max + 1}`;
}

const emptySolar = (list) => ({
  id: nextId("S", list),
  power_output_mw: "",
});
const emptyWind = (list) => ({
  id: nextId("W", list),
  power_output_mw: "",
});
const emptyBattery = (list) => ({
  id: nextId("B", list),
  capacity_mwh: "",
  max_rate_mw: "",
  min_soc_pct: "10",
  max_soc_pct: "95",
  initial_soc_pct: "50",
  showAdvanced: false,
});
const emptyConsumer = (list) => ({
  id: nextId("C", list),
  day_load_mw: "",
  night_load_mw: "",
  shift_start: "06:00",
  shift_end: "22:00",
});

export default function ProjectForm({ onCreated }) {
  const [name, setName] = useState("");
  const [solarFarms, setSolarFarms] = useState([emptySolar([])]);
  const [windFarms, setWindFarms] = useState([emptyWind([])]);
  const [batteries, setBatteries] = useState([emptyBattery([])]);
  const [consumers, setConsumers] = useState([emptyConsumer([])]);
  const [grid, setGrid] = useState({
    line_limit_mw: "",
    buy_premium_per_kwh: "",
    price_cap_per_kwh: "",
    emission_tco2_per_mwh: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});

  function updateList(list, setList, idx, field, value) {
    const copy = [...list];
    copy[idx] = { ...copy[idx], [field]: value };
    setList(copy);
  }

  function removeFromList(list, setList, idx) {
    if (list.length <= 1) return;
    setList(list.filter((_, i) => i !== idx));
  }

  const collectAllIds = useCallback(() => {
    return [
      ...solarFarms.map((r) => r.id),
      ...windFarms.map((r) => r.id),
      ...batteries.map((r) => r.id),
      ...consumers.map((r) => r.id),
    ];
  }, [solarFarms, windFarms, batteries, consumers]);

  function validateClient() {
    const errs = {};
    if (!name.trim()) errs.name = "Project name is required";

    const hasConsumer = consumers.some(
      (c) => c.id && c.day_load_mw && c.night_load_mw
    );
    if (!hasConsumer) {
      errs.consumers = "At least one consumer is required";
    }

    const lineLimit = grid.line_limit_mw === "" ? null : Number(grid.line_limit_mw);
    if (lineLimit === null || isNaN(lineLimit) || lineLimit < 0) {
      errs.grid_limit = "Line limit is required (>= 0, 0 = islanded)";
    }

    const hasSolar = solarFarms.some((s) => s.id && s.power_output_mw);
    const hasWind = windFarms.some((w) => w.id && w.power_output_mw);
    const hasBattery = batteries.some((b) => b.id && b.capacity_mwh && b.max_rate_mw);
    const hasGridImport = lineLimit > 0;
    if (!hasSolar && !hasWind && !hasBattery && !hasGridImport) {
      errs.supply = "Need at least one supply path: a farm, battery, or line limit > 0";
    }

    solarFarms.forEach((sf, i) => {
      if (sf.id && sf.power_output_mw && Number(sf.power_output_mw) <= 0)
        errs[`solar_${i}_mw`] = "Must be > 0";
    });
    windFarms.forEach((wf, i) => {
      if (wf.id && wf.power_output_mw && Number(wf.power_output_mw) <= 0)
        errs[`wind_${i}_mw`] = "Must be > 0";
    });
    batteries.forEach((bat, i) => {
      if (bat.id && bat.capacity_mwh && Number(bat.capacity_mwh) <= 0)
        errs[`bat_${i}_cap`] = "Must be > 0";
      if (bat.id && bat.max_rate_mw && Number(bat.max_rate_mw) <= 0)
        errs[`bat_${i}_rate`] = "Must be > 0";
      const minS = Number(bat.min_soc_pct);
      const maxS = Number(bat.max_soc_pct);
      const initS = Number(bat.initial_soc_pct);
      if (bat.id && bat.capacity_mwh) {
        if (minS >= initS)
          errs[`bat_${i}_minsoc`] = "Must be < initial SOC";
        if (initS >= maxS)
          errs[`bat_${i}_maxsoc`] = "Must be > initial SOC";
      }
    });
    consumers.forEach((con, i) => {
      if (con.id && con.day_load_mw && Number(con.day_load_mw) <= 0)
        errs[`con_${i}_day`] = "Must be > 0";
      if (con.id && con.night_load_mw && Number(con.night_load_mw) <= 0)
        errs[`con_${i}_night`] = "Must be > 0";
      if (con.shift_start && !/^\d{2}:\d{2}$/.test(con.shift_start))
        errs[`con_${i}_start`] = "HH:MM format";
      if (con.shift_end && !/^\d{2}:\d{2}$/.test(con.shift_end))
        errs[`con_${i}_end`] = "HH:MM format";
    });


    const allIds = collectAllIds().filter(Boolean);
    const seen = new Set();
    const dupes = new Set();
    allIds.forEach((id) => {
      if (seen.has(id)) dupes.add(id);
      seen.add(id);
    });
    if (dupes.size > 0) errs.duplicates = `Duplicate IDs: ${[...dupes].join(", ")}`;

    return errs;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setFieldErrors({});

    const errs = validateClient();
    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs);
      return;
    }

    setSubmitting(true);

    const payload = {
      name: name.trim(),
      solar_farms: solarFarms
        .filter((s) => s.id && s.power_output_mw)
        .map((s) => ({
          id: s.id,
          power_output_mw: Number(s.power_output_mw),
        })),
      wind_farms: windFarms
        .filter((w) => w.id && w.power_output_mw)
        .map((w) => ({
          id: w.id,
          power_output_mw: Number(w.power_output_mw),
        })),
      batteries: batteries
        .filter((b) => b.id && b.capacity_mwh && b.max_rate_mw)
        .map((b) => ({
          id: b.id,
          capacity_mwh: Number(b.capacity_mwh),
          max_rate_mw: Number(b.max_rate_mw),
          min_soc_pct: Number(b.min_soc_pct),
          max_soc_pct: Number(b.max_soc_pct),
          initial_soc_pct: Number(b.initial_soc_pct),
        })),
      consumers: consumers
        .filter((c) => c.id && c.day_load_mw && c.night_load_mw)
        .map((c) => ({
          id: c.id,
          day_load_mw: Number(c.day_load_mw),
          night_load_mw: Number(c.night_load_mw),
          shift_start: c.shift_start,
          shift_end: c.shift_end,
        })),
    };

    payload.grid = {
      line_limit_mw: Number(grid.line_limit_mw) || 0,
      buy_premium_per_kwh: Number(grid.buy_premium_per_kwh) || 0,
      price_cap_per_kwh: Number(grid.price_cap_per_kwh) || 0,
      emission_tco2_per_mwh: Number(grid.emission_tco2_per_mwh) || 0,
    };

    try {
      await createProjectFull(payload);
      setName("");
      setSolarFarms([emptySolar([])]);
      setWindFarms([emptyWind([])]);
      setBatteries([emptyBattery([])]);
      setConsumers([emptyConsumer([])]);
      setGrid({
        line_limit_mw: "",
        buy_premium_per_kwh: "",
        price_cap_per_kwh: "",
        emission_tco2_per_mwh: "",
      });
      onCreated();
    } catch (err) {
      if (err.detail) {
        if (typeof err.detail === "string") {
          setError(err.detail);
        } else if (Array.isArray(err.detail)) {
          const parsed = {};
          const topErrors = [];
          err.detail.forEach((d) => {
            const loc = d.loc?.join(".") || "general";
            if (loc === "body" || loc === "general") {
              topErrors.push(d.msg.replace(/^Value error, /, ""));
            } else {
              parsed[loc] = d.msg;
            }
          });
          setFieldErrors(parsed);
          setError(topErrors.length > 0 ? topErrors.join("; ") : "Please fix the errors below");
        } else {
          setError(JSON.stringify(err.detail));
        }
      } else {
        setError(err.message || "Failed to create project");
      }
    } finally {
      setSubmitting(false);
    }
  }

  const FieldError = ({ id }) => {
    const msg = fieldErrors[id];
    return msg ? <div className="field-error">{msg}</div> : null;
  };

  return (
    <form className="project-form" onSubmit={handleSubmit}>
      <h2>Add New Project</h2>

      {error && <div className="form-error">{error}</div>}
      {fieldErrors.duplicates && (
        <div className="form-error">{fieldErrors.duplicates}</div>
      )}
      {fieldErrors.supply && (
        <div className="form-error">{fieldErrors.supply}</div>
      )}

      <label>
        Project Name
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. farm 1"
        />
        <FieldError id="name" />
      </label>

      {/* Solar Farms */}
      <fieldset>
        <legend>Solar Farms</legend>
        <FieldError id="farms" />
        {solarFarms.map((sf, i) => (
          <div key={i}>
            <div className="inline-row">
              <input
                type="text"
                placeholder="ID"
                value={sf.id}
                onChange={(e) =>
                  updateList(solarFarms, setSolarFarms, i, "id", e.target.value)
                }
                className="input-id"
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
            <FieldError id={`solar_${i}_mw`} />
          </div>
        ))}
        <button
          type="button"
          className="btn-add"
          onClick={() =>
            setSolarFarms([...solarFarms, emptySolar(solarFarms)])
          }
        >
          + Add Solar Farm
        </button>
      </fieldset>

      {/* Wind Farms */}
      <fieldset>
        <legend>Wind Farms</legend>
        {windFarms.map((wf, i) => (
          <div key={i}>
            <div className="inline-row">
              <input
                type="text"
                placeholder="ID"
                value={wf.id}
                onChange={(e) =>
                  updateList(windFarms, setWindFarms, i, "id", e.target.value)
                }
                className="input-id"
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
            <FieldError id={`wind_${i}_mw`} />
          </div>
        ))}
        <button
          type="button"
          className="btn-add"
          onClick={() => setWindFarms([...windFarms, emptyWind(windFarms)])}
        >
          + Add Wind Farm
        </button>
      </fieldset>

      {/* Batteries */}
      <fieldset>
        <legend>Batteries</legend>
        {batteries.map((bat, i) => (
          <div key={i} className="battery-block">
            <div className="inline-row">
              <input
                type="text"
                placeholder="ID"
                value={bat.id}
                onChange={(e) =>
                  updateList(batteries, setBatteries, i, "id", e.target.value)
                }
                className="input-id"
              />
              <input
                type="number"
                placeholder="Capacity (MWh)"
                value={bat.capacity_mwh}
                onChange={(e) =>
                  updateList(
                    batteries,
                    setBatteries,
                    i,
                    "capacity_mwh",
                    e.target.value
                  )
                }
              />
              <input
                type="number"
                placeholder="Max Rate (MW)"
                value={bat.max_rate_mw}
                onChange={(e) =>
                  updateList(
                    batteries,
                    setBatteries,
                    i,
                    "max_rate_mw",
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
            <FieldError id={`bat_${i}_cap`} />
            <FieldError id={`bat_${i}_rate`} />
            <button
              type="button"
              className="btn-toggle-advanced"
              onClick={() =>
                updateList(
                  batteries,
                  setBatteries,
                  i,
                  "showAdvanced",
                  !bat.showAdvanced
                )
              }
            >
              {bat.showAdvanced ? "▾ Advanced" : "▸ Advanced"}
            </button>
            {bat.showAdvanced && (
              <div className="advanced-fields">
                <label>
                  Min SOC %
                  <input
                    type="number"
                    value={bat.min_soc_pct}
                    onChange={(e) =>
                      updateList(
                        batteries,
                        setBatteries,
                        i,
                        "min_soc_pct",
                        e.target.value
                      )
                    }
                    min="0"
                    max="100"
                  />
                </label>
                <label>
                  Max SOC %
                  <input
                    type="number"
                    value={bat.max_soc_pct}
                    onChange={(e) =>
                      updateList(
                        batteries,
                        setBatteries,
                        i,
                        "max_soc_pct",
                        e.target.value
                      )
                    }
                    min="0"
                    max="100"
                  />
                </label>
                <label>
                  Initial SOC %
                  <input
                    type="number"
                    value={bat.initial_soc_pct}
                    onChange={(e) =>
                      updateList(
                        batteries,
                        setBatteries,
                        i,
                        "initial_soc_pct",
                        e.target.value
                      )
                    }
                    min="0"
                    max="100"
                  />
                </label>
                <FieldError id={`bat_${i}_minsoc`} />
                <FieldError id={`bat_${i}_maxsoc`} />
              </div>
            )}
          </div>
        ))}
        <button
          type="button"
          className="btn-add"
          onClick={() =>
            setBatteries([...batteries, emptyBattery(batteries)])
          }
        >
          + Add Battery
        </button>
      </fieldset>

      {/* Industrial Consumers */}
      <fieldset>
        <legend>Industrial Consumers</legend>
        <FieldError id="consumers" />
        {consumers.map((con, i) => (
          <div key={i}>
            <div className="inline-row consumer-row">
              <input
                type="text"
                placeholder="ID"
                value={con.id}
                onChange={(e) =>
                  updateList(consumers, setConsumers, i, "id", e.target.value)
                }
                className="input-id"
              />
              <input
                type="number"
                placeholder="Day (MW)"
                value={con.day_load_mw}
                onChange={(e) =>
                  updateList(
                    consumers,
                    setConsumers,
                    i,
                    "day_load_mw",
                    e.target.value
                  )
                }
              />
              <input
                type="number"
                placeholder="Night (MW)"
                value={con.night_load_mw}
                onChange={(e) =>
                  updateList(
                    consumers,
                    setConsumers,
                    i,
                    "night_load_mw",
                    e.target.value
                  )
                }
              />
              <input
                type="text"
                placeholder="Start"
                value={con.shift_start}
                onChange={(e) =>
                  updateList(
                    consumers,
                    setConsumers,
                    i,
                    "shift_start",
                    e.target.value
                  )
                }
                className="input-time"
              />
              <input
                type="text"
                placeholder="End"
                value={con.shift_end}
                onChange={(e) =>
                  updateList(
                    consumers,
                    setConsumers,
                    i,
                    "shift_end",
                    e.target.value
                  )
                }
                className="input-time"
              />
              <button
                type="button"
                className="btn-icon remove"
                onClick={() => removeFromList(consumers, setConsumers, i)}
                title="Remove"
              >
                &times;
              </button>
            </div>
            <FieldError id={`con_${i}_day`} />
            <FieldError id={`con_${i}_night`} />
            <FieldError id={`con_${i}_start`} />
            <FieldError id={`con_${i}_end`} />
          </div>
        ))}
        <button
          type="button"
          className="btn-add"
          onClick={() =>
            setConsumers([...consumers, emptyConsumer(consumers)])
          }
        >
          + Add Consumer
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
            <FieldError id="grid_limit" />
          </label>
          <label>
            Buy Premium (₹/kWh)
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
            Price Cap (₹/kWh)
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
