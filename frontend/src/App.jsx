import { useState } from "react";
import ProjectForm from "./components/ProjectForm";
import ProjectTable from "./components/ProjectTable";
import "./App.css";

export default function App() {
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Renewable Energy Manager</h1>
      </header>
      <main className="app-main">
        <aside className="panel-form">
          <ProjectForm onCreated={() => setRefreshKey((k) => k + 1)} />
        </aside>
        <section className="panel-table">
          <ProjectTable refreshKey={refreshKey} />
        </section>
      </main>
    </div>
  );
}
