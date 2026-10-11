import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

export default function PriceChart({ ticks }) {
  const data = useMemo(
    () =>
      ticks.map((t) => ({
        time: t.timestamp,
        Price: t.actuals.price_per_kwh,
      })),
    [ticks]
  );

  return (
    <div className="chart-card">
      <h3>Grid Price (INR/kWh)</h3>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="time" tick={{ fontSize: 11 }} interval={7} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Line
            dataKey="Price"
            stroke="#7c3aed"
            dot={false}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
