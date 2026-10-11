import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

export default function DispatchChart({ ticks }) {
  const data = useMemo(
    () =>
      ticks.map((t) => ({
        time: t.timestamp,
        Discharge: t.dispatch.discharge,
        Buy: t.dispatch.buy,
        Unmet: t.dispatch.unmet,
        Charge: -t.dispatch.charge,
        Sell: -t.dispatch.sell,
        Curtail: -t.dispatch.curtail,
      })),
    [ticks]
  );

  return (
    <div className="chart-card">
      <h3>Dispatch (MW)</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} stackOffset="sign">
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="time" tick={{ fontSize: 11 }} interval={7} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Legend />
          <Bar dataKey="Discharge" stackId="a" fill="#16a34a" />
          <Bar dataKey="Buy" stackId="a" fill="#7c3aed" />
          <Bar dataKey="Unmet" stackId="a" fill="#dc2626" />
          <Bar dataKey="Charge" stackId="a" fill="#2563eb" />
          <Bar dataKey="Sell" stackId="a" fill="#06b6d4" />
          <Bar dataKey="Curtail" stackId="a" fill="#9ca3af" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
