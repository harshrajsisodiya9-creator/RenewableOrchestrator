"""Pure function: builds features shared between the day planner and LP optimizer."""

from __future__ import annotations

DT = 0.25


def build_features(
    forecast_96: dict[str, list[float]],
    telemetry: dict,
    alerts: list[str],
) -> dict:
    """Return derived features from 96-tick forecasts, battery telemetry, and alerts.

    forecast_96 keys: 'solar', 'wind', 'demand', 'price' — each a list of up to 96 floats.
    telemetry keys: 'soc_pct', 'soc_mwh'.
    alerts: list of raw alert text strings.
    """
    solar = forecast_96.get("solar", [])
    wind = forecast_96.get("wind", [])
    demand = forecast_96.get("demand", [])
    price = forecast_96.get("price", [])

    N = min(96, len(solar), len(wind), len(demand), len(price))
    if N == 0:
        return _empty_features(telemetry, alerts)

    # ── hourly summary (up to 24 rows) ───────────────────────────────────
    hourly_summary: list[dict] = []
    for h in range(24):
        start = h * 4
        end = min(start + 4, N)
        if start >= N:
            break
        n_ticks = end - start
        if n_ticks == 0:
            break
        avg_price = sum(price[k] for k in range(start, end)) / n_ticks
        avg_demand = sum(demand[k] for k in range(start, end)) / n_ticks
        avg_solar = sum(solar[k] for k in range(start, end)) / n_ticks
        avg_wind = sum(wind[k] for k in range(start, end)) / n_ticks
        net_mw = (avg_solar + avg_wind) - avg_demand
        hourly_summary.append({
            "hour": h,
            "avg_price": round(avg_price, 4),
            "avg_demand_mw": round(avg_demand, 1),
            "avg_solar_mw": round(avg_solar, 1),
            "avg_wind_mw": round(avg_wind, 1),
            "net_mw": round(net_mw, 1),
        })

    # ── peak ticks: top 25 % by price ────────────────────────────────────
    prices = price[:N]
    n_peak = max(1, N // 4)
    price_threshold = sorted(prices, reverse=True)[n_peak - 1]
    peak_ticks = [k for k in range(N) if prices[k] >= price_threshold]

    if peak_ticks:
        peak_window = (peak_ticks[0], peak_ticks[-1])
        peak_avg_price = sum(prices[k] for k in peak_ticks) / len(peak_ticks)
    else:
        peak_window = (0, 0)
        peak_avg_price = 0.0

    # ── e_need: unmet-by-renewables energy during peak ticks ─────────────
    e_need_mwh = sum(
        max(demand[k] - solar[k] - wind[k], 0) * DT for k in peak_ticks
    )

    # ── cheapest 4-hour window ───────────────────────────────────────────
    if len(hourly_summary) >= 4:
        best_start = 0
        best_avg = float("inf")
        for i in range(len(hourly_summary) - 3):
            avg = sum(h["avg_price"] for h in hourly_summary[i : i + 4]) / 4
            if avg < best_avg:
                best_avg = avg
                best_start = hourly_summary[i]["hour"]
        cheapest_window = (best_start, best_start + 4)
    else:
        cheapest_window = (0, 0)

    # ── midday surplus (10:00–15:00) ─────────────────────────────────────
    midday_surplus_mwh = sum(
        max(solar[k] + wind[k] - demand[k], 0) * DT
        for k in range(N)
        if 40 <= k < 60  # ticks 40–59 = 10:00–14:45
    )

    return {
        "hourly_summary": hourly_summary,
        "peak_window": peak_window,
        "peak_ticks": peak_ticks,
        "peak_avg_price": round(peak_avg_price, 4),
        "e_need_mwh": round(e_need_mwh, 1),
        "cheapest_window": cheapest_window,
        "midday_surplus_mwh": round(midday_surplus_mwh, 1),
        "soc_pct": telemetry.get("soc_pct", 0),
        "soc_mwh": telemetry.get("soc_mwh", 0),
        "alerts": alerts,
    }


def _empty_features(telemetry: dict, alerts: list[str]) -> dict:
    return {
        "hourly_summary": [],
        "peak_window": (0, 0),
        "peak_ticks": [],
        "peak_avg_price": 0.0,
        "e_need_mwh": 0.0,
        "cheapest_window": (0, 0),
        "midday_surplus_mwh": 0.0,
        "soc_pct": telemetry.get("soc_pct", 0),
        "soc_mwh": telemetry.get("soc_mwh", 0),
        "alerts": alerts,
    }
