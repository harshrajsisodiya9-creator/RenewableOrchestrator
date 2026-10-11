import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

export default function BatteryChart({ ticks }) {
  const data = useMemo(
    () =>
      ticks.map((t) => ({
        time: t.timestamp,
        SOC: t.battery_soc_pct,
        reserve: t.supervisor?.reserve_target_pct ?? 20,
      })),
    [ticks]
  );

  const lastReserve = data.length > 0 ? data[data.length - 1].reserve : 20;

  return (
    <div className="chart-card">
      <h3>Battery SOC (%)</h3>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="time" tick={{ fontSize: 11 }} interval={7} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
          <Tooltip />
          <ReferenceLine
            y={lastReserve}
            stroke="#dc2626"
            strokeDasharray="5 5"
            label={{ value: "Reserve", fill: "#dc2626", fontSize: 10 }}
          />
          <Area
            dataKey="SOC"
            stroke="#16a34a"
            fill="#dcfce7"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
