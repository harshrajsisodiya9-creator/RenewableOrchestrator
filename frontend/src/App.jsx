import { useState, useEffect, useRef, useCallback } from "react";
import { BrowserRouter, Routes, Route, useParams, useLocation } from "react-router-dom";
import ProjectForm from "./components/ProjectForm";
import ProjectTable from "./components/ProjectTable";
import ControlBar from "./components/ControlBar";
import StartForm from "./components/StartForm";
import GenerationChart from "./components/GenerationChart";
import DispatchChart from "./components/DispatchChart";
import BatteryChart from "./components/BatteryChart";
import PriceChart from "./components/PriceChart";
import EventTimeline from "./components/EventTimeline";
import SupervisorFeed from "./components/SupervisorFeed";
import EventPanel from "./components/EventPanel";
import InjectPanel from "./components/InjectPanel";
import CapacityBar from "./components/CapacityBar";
import Scorecard from "./components/Scorecard";
import {
  fetchProjects,
  fetchProjectDetail,
  startSimulation,
  pauseSimulation,
  playSimulation,
  stepSimulation,
  setSimulationSpeed,
  resetSimulation,
  getSimulationStatus,
  getTickResults,
  listEvents,
} from "./api";
import "./App.css";

function BuilderPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey((k) => k + 1);

  return (
    <main className="app-main">
      <aside className="panel-form">
        <ProjectForm onCreated={refresh} />
      </aside>
      <section className="panel-table">
        <ProjectTable refreshKey={refreshKey} onRefresh={refresh} />
      </section>
    </main>
  );
}

function SimulatePage() {
  const { projectId } = useParams();
  const location = useLocation();
  const pid = Number(projectId);

  const [project, setProject] = useState(null);
  const [simStatus, setSimStatus] = useState(null);
  const [ticks, setTicks] = useState([]);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState("");
  const lastTickRef = useRef(-1);
  const pollRef = useRef(null);
  const pollCountRef = useRef(0);

  useEffect(() => {
    async function loadProject() {
      try {
        const name = location.state?.projectName;
        if (name) {
          setProject(await fetchProjectDetail(name));
        } else {
          const all = await fetchProjects();
          const match = all.find((p) => p.id === pid);
          if (match) setProject(await fetchProjectDetail(match.name));
          else setError("Project not found");
        }
      } catch {
        setError("Failed to load project");
      }
    }
    loadProject();
  }, [pid, location.state?.projectName]);

  useEffect(() => {
    getSimulationStatus(pid).then((s) => {
      if (s) {
        setSimStatus(s);
        getTickResults(pid, -1).then((t) => {
          setTicks(t);
          lastTickRef.current = t.length > 0 ? Math.max(...t.map((x) => x.tick)) : -1;
        });
      }
    });
    listEvents(pid).then(setEvents).catch(() => {});
  }, [pid]);

  const poll = useCallback(async () => {
    try {
      const status = await getSimulationStatus(pid);
      if (status) {
        setSimStatus(status);
        const newTicks = await getTickResults(pid, lastTickRef.current);
        if (newTicks.length > 0) {
          setTicks((prev) => [...prev, ...newTicks]);
          lastTickRef.current = Math.max(...newTicks.map((t) => t.tick));
        }
        pollCountRef.current++;
        if (pollCountRef.current % 3 === 0) {
          listEvents(pid).then(setEvents).catch(() => {});
        }
      }
    } catch { /* ignore poll errors */ }
  }, [pid]);

  useEffect(() => {
    const status = simStatus?.status;
    if (status === "playing" || status === "paused") {
      pollRef.current = setInterval(poll, 1000);
      return () => clearInterval(pollRef.current);
    }
  }, [simStatus?.status, poll]);

  async function handleStart(opts) {
    setError("");
    try {
      const s = await startSimulation(pid, opts);
      setSimStatus(s);
      setTicks([]);
      lastTickRef.current = -1;
      listEvents(pid).then(setEvents).catch(() => {});
    } catch (err) {
      setError(err.message);
    }
  }

  async function handlePause() {
    try { await pauseSimulation(pid); setSimStatus((s) => ({ ...s, status: "paused" })); } catch {}
  }
  async function handlePlay() {
    try { await playSimulation(pid); setSimStatus((s) => ({ ...s, status: "playing" })); } catch {}
  }
  async function handleStep() {
    try { await stepSimulation(pid); } catch {}
  }
  async function handleSpeed(speed) {
    try { await setSimulationSpeed(pid, speed); setSimStatus((s) => ({ ...s, speed })); } catch {}
  }
  async function handleReset() {
    try {
      await resetSimulation(pid);
      setSimStatus(null);
      setTicks([]);
      lastTickRef.current = -1;
      setEvents([]);
    } catch {}
  }
  function handleEventChange() {
    listEvents(pid).then(setEvents).catch(() => {});
  }

  const isIdle = !simStatus || simStatus.status === "idle";
  const isCompleted = simStatus?.status === "completed";

  return (
    <div className="sim-page">
      <ControlBar
        project={project}
        simStatus={simStatus}
        onPause={handlePause}
        onPlay={handlePlay}
        onStep={handleStep}
        onSpeedChange={handleSpeed}
        onReset={handleReset}
      />

      {error && <div className="form-error">{error}</div>}

      {isIdle && <StartForm onStart={handleStart} disabled={!project} />}

      {!isIdle && (
        <div className="sim-content">
          <div className="sim-charts">
            <CapacityBar project={project} />
            <GenerationChart ticks={ticks} />
            <DispatchChart ticks={ticks} />
            <BatteryChart ticks={ticks} />
            <PriceChart ticks={ticks} />
            <EventTimeline events={events} currentTick={simStatus?.current_tick ?? -1} />
            {isCompleted && <Scorecard ticks={ticks} />}
          </div>
          <div className="sim-sidebar">
            <SupervisorFeed ticks={ticks} />
            <EventPanel
              projectId={pid}
              events={events}
              onEventChange={handleEventChange}
              currentTick={simStatus?.current_tick ?? -1}
            />
            <InjectPanel project={project} />
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <h1>Renewable Energy Manager</h1>
        </header>
        <Routes>
          <Route path="/" element={<BuilderPage />} />
          <Route path="/projects/:projectId/simulate" element={<SimulatePage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
