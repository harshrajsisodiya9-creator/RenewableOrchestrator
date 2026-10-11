import { Link } from "react-router-dom";

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16];

export default function ControlBar({
  project,
  simStatus,
  onPause,
  onPlay,
  onStep,
  onSpeedChange,
  onReset,
}) {
  const status = simStatus?.status || "idle";
  const tick = simStatus?.current_tick ?? 0;
  const hh = String(Math.floor(tick / 4)).padStart(2, "0");
  const mm = String((tick % 4) * 15).padStart(2, "0");
  const isPlaying = status === "playing";
  const isPaused = status === "paused";
  const isActive = isPlaying || isPaused;

  return (
    <div className="control-bar">
      <Link to="/" className="back-link">
        &larr; Projects
      </Link>
      <span className="project-name">{project?.name}</span>
      <span className={`badge badge-mode`}>{simStatus?.mode || "—"}</span>
      <span className="tick-display">
        Tick {tick}/96 ({hh}:{mm})
      </span>
      <span className={`badge badge-${status}`}>{status}</span>

      {isActive && (
        <div className="controls">
          {isPlaying ? (
            <button className="btn-control" onClick={onPause}>
              Pause
            </button>
          ) : (
            <button className="btn-control" onClick={onPlay}>
              Play
            </button>
          )}
          <button className="btn-control" onClick={onStep} disabled={isPlaying}>
            Step
          </button>
          <select
            className="speed-select"
            value={simStatus?.speed ?? 1}
            onChange={(e) => onSpeedChange(parseFloat(e.target.value))}
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}x
              </option>
            ))}
          </select>
          <button
            className="btn-control btn-danger"
            onClick={() => confirm("Reset simulation?") && onReset()}
          >
            Reset
          </button>
        </div>
      )}

      {status === "completed" && (
        <button className="btn-control btn-new-day" onClick={onReset}>
          New Day
        </button>
      )}
    </div>
  );
}
