import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

export default function GenerationChart({ ticks }) {
  const data = useMemo(
    () =>
      ticks.map((t) => ({
        time: t.timestamp,
        Solar: t.actuals.solar_mw,
        Wind: t.actuals.wind_mw,
        Demand: t.actuals.demand_mw,
      })),
    [ticks]
  );

  return (
    <div className="chart-card">
      <h3>Generation vs Demand (MW)</h3>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="time" tick={{ fontSize: 11 }} interval={7} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Legend />
          <Line dataKey="Solar" stroke="#f59e0b" dot={false} strokeWidth={2} />
          <Line dataKey="Wind" stroke="#06b6d4" dot={false} strokeWidth={2} />
          <Line dataKey="Demand" stroke="#dc2626" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
