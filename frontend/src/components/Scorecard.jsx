import { useMemo } from "react";

const DT = 0.25;

export default function Scorecard({ ticks }) {
  const metrics = useMemo(() => {
    if (ticks.length === 0) return null;

    let totalCost = 0;
    let totalCarbon = 0;
    let totalDemandMwh = 0;
    let totalUnmetMwh = 0;
    let totalCurtailMwh = 0;
    let peakUnmet = 0;

    for (const t of ticks) {
      const d = t.dispatch;
      const a = t.actuals;
      totalCost += d.cash_cost_inr ?? (d.buy * DT * (a.price_per_kwh + 0.5) * 1000 - d.sell * DT * a.price_per_kwh * 1000);
      totalCarbon += d.carbon_tonnes ?? d.buy * DT * 0.71;
      totalDemandMwh += a.demand_mw * DT;
      totalUnmetMwh += d.unmet * DT;
      totalCurtailMwh += d.curtail * DT;
      peakUnmet = Math.max(peakUnmet, d.unmet);
    }

    const reliability = totalDemandMwh > 0
      ? ((1 - totalUnmetMwh / totalDemandMwh) * 100).toFixed(1)
      : "100.0";

    const lastTick = ticks[ticks.length - 1];

    return {
      cost: totalCost.toFixed(0),
      carbon: totalCarbon.toFixed(2),
      reliability,
      curtailment: totalCurtailMwh.toFixed(1),
      peakUnmet: peakUnmet.toFixed(1),
      finalSoc: lastTick.battery_soc_pct.toFixed(1),
    };
  }, [ticks]);

  if (!metrics) return null;

  return (
    <div className="scorecard">
      <div className="metric-card">
        <span className="metric-value">₹{metrics.cost}</span>
        <span className="metric-label">Total Cost</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{metrics.carbon} t</span>
        <span className="metric-label">Carbon</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{metrics.reliability}%</span>
        <span className="metric-label">Reliability</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{metrics.curtailment} MWh</span>
        <span className="metric-label">Curtailed</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{metrics.peakUnmet} MW</span>
        <span className="metric-label">Peak Unmet</span>
      </div>
      <div className="metric-card">
        <span className="metric-value">{metrics.finalSoc}%</span>
        <span className="metric-label">Final SOC</span>
      </div>
    </div>
  );
}
