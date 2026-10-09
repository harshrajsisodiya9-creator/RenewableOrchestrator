const API = "http://localhost:8000";

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
