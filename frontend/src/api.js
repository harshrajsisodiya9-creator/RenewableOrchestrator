const API = "/api";

export async function fetchProjects() {
  const res = await fetch(`${API}/projects/`);
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function fetchProjectDetail(name) {
  const res = await fetch(`${API}/projects/${encodeURIComponent(name)}`);
  if (!res.ok) throw new Error(`Failed to fetch project '${name}'`);
  return res.json();
}

export async function createProject(name) {
  const res = await fetch(`${API}/projects/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create project");
  }
  return res.json();
}

export async function createProjectFull(data) {
  const res = await fetch(`${API}/projects/full`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw err;
  }
  return res.json();
}

export async function createSolarFarm(data) {
  const res = await fetch(`${API}/solar-farms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create solar farm");
  }
  return res.json();
}

export async function createWindFarm(data) {
  const res = await fetch(`${API}/wind-farms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create wind farm");
  }
  return res.json();
}

export async function createBattery(data) {
  const res = await fetch(`${API}/batteries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create battery");
  }
  return res.json();
}

export async function createConsumer(data) {
  const res = await fetch(`${API}/consumers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create consumer");
  }
  return res.json();
}

export async function createGrid(data) {
  const res = await fetch(`${API}/grids/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create grid");
  }
  return res.json();
}

export async function deleteProject(id) {
  const res = await fetch(`${API}/projects/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to delete project");
  }
}

export async function startSimulation(projectId, { mode, seed, scenario }) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, seed, scenario }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to start simulation");
  }
  return res.json();
}

export async function pauseSimulation(projectId) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/pause`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to pause");
  return res.json();
}

export async function playSimulation(projectId) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/play`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to play");
  return res.json();
}

export async function stepSimulation(projectId) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/step`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to step");
  return res.json();
}

export async function setSimulationSpeed(projectId, speed) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/speed?speed=${speed}`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to set speed");
  return res.json();
}

export async function resetSimulation(projectId) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/reset`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to reset");
  return res.json();
}

export async function getSimulationStatus(projectId) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/status`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to fetch status");
  return res.json();
}

export async function getTickResults(projectId, afterTick = -1) {
  const res = await fetch(`${API}/projects/${projectId}/simulation/ticks?after=${afterTick}`);
  if (!res.ok) throw new Error("Failed to fetch ticks");
  return res.json();
}

export async function createEvent(projectId, data) {
  const res = await fetch(`${API}/projects/${projectId}/events/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to create event");
  }
  return res.json();
}

export async function listEvents(projectId) {
  const res = await fetch(`${API}/projects/${projectId}/events/`);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

export async function deleteEvent(projectId, eventId) {
  const res = await fetch(`${API}/projects/${projectId}/events/${eventId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Failed to delete event");
  }
}

export async function injectFault(data) {
  const res = await fetch(`${API}/inject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    let detail = "Failed to inject fault";
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}
