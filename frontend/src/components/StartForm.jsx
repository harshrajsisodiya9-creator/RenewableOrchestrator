import { useState } from "react";

export default function StartForm({ onStart, disabled }) {
  const [mode, setMode] = useState("reliability");
  const [seed, setSeed] = useState(42);
  const [scenario, setScenario] = useState("blank");

  function handleSubmit(e) {
    e.preventDefault();
    onStart({ mode, seed: Number(seed), scenario });
  }

  return (
    <form className="start-form" onSubmit={handleSubmit}>
      <h3>Start Simulation</h3>
      <div className="start-fields">
        <label>
          Mode
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="reliability">Reliability</option>
            <option value="profit">Profit</option>
            <option value="clean">Clean</option>
          </select>
        </label>
        <label>
          Seed
          <input
            type="number"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
          />
        </label>
        <label>
          Scenario
          <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
            <option value="blank">Blank</option>
            <option value="may_storm">May Storm</option>
          </select>
        </label>
      </div>
      <button className="btn-submit" type="submit" disabled={disabled}>
        Start Day
      </button>
    </form>
  );
}
