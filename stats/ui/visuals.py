# stats/ui/visuals.py
from __future__ import annotations
import json
import os
import io
from typing import Iterable, List, Dict, Any, Optional, Tuple
from datetime import datetime
import discord
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

# -----------------------
# Generic helpers
# -----------------------
def _fmt_compact(n: float) -> str:
    """Compact number formatting (English style: k, M, B)."""
    try:
        n = float(n)
    except Exception:
        return str(n)

    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}k"
    else:
        return str(int(n)) if n.is_integer() else str(n)

def _annotate_bars(ax, bars, values):
    for rect, v in zip(bars, values):
        try:
            height = rect.get_height()
            if height <= 0:
                continue
            ax.text(
                rect.get_x() + rect.get_width() / 2.0,
                height,
                f"{_fmt_compact(v)}",
                ha="center",
                va="bottom",
                fontsize=8,
                rotation=0,
            )
        except Exception:
            pass

def _metric_color(metric: str) -> tuple[float, float, float]:
    m = (metric or "").lower()
    if m == "shiny":
        return (1.0, 0.9, 0.2)  # yellow
    if m == "iv100":
        return (0.2, 0.8, 0.2)
    if m == "iv0":
        return (0.9, 0.3, 0.3)
    if m == "pvp_little":
        return (0.4, 0.6, 0.9)
    if m == "pvp_great":
        return (0.4, 0.4, 0.9)
    if m == "pvp_ultra":
        return (0.3, 0.3, 0.7)
    return (0.6, 0.6, 0.6)

# cache for id->name mapping
_ID_NAME_MAP: dict[str, str] | None = None
_FORM_REV: dict[str, str] | None = None  # "0"->"FORM_UNSET", ...

def _load_id_maps() -> tuple[dict[str, str], dict[str, str]]:
    """
    Loads id_to_name.json and returns:
      pokemon_map: {"821": "Rookidee", ...}
      form_rev:    {"0": "FORM_UNSET", ...}   # reverse map of 'form' ids to enum name
    """
    global _ID_NAME_MAP, _FORM_REV
    if _ID_NAME_MAP is not None and _FORM_REV is not None:
        return _ID_NAME_MAP, _FORM_REV

    # Try a few likely locations
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "stats", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "id_to_name.json"),
    ]
    data = None
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                break
        except Exception:
            continue

    # If not found, use empty maps (labels will stay as 'pid:form')
    pokemon_map = {}
    form_rev = {}
    if isinstance(data, dict):
        pokemon_map = {str(k): str(v) for k, v in (data.get("pokemon") or {}).items()}
        # reverse the 'form' map: enum_name -> "id"  ==>  "id" -> enum_name
        raw_forms = data.get("form") or {}
        form_rev = {str(v): str(k) for k, v in raw_forms.items()}

    _ID_NAME_MAP, _FORM_REV = pokemon_map, form_rev
    return pokemon_map, form_rev


def _pidform_label(pid_form: str) -> str:
    """
    pid_form is like '821:0'. Convert to 'Rookidee (FORM_UNSET)' if we can.
    """
    try:
        pid_s, form_s = str(pid_form).split(":", 1)
    except ValueError:
        return str(pid_form)
    pmap, frev = _load_id_maps()
    pname = pmap.get(pid_s, pid_s)
    fenum = frev.get(form_s, form_s)
    # Make the form a bit friendlier; keep enum if you prefer exact
    return f"{pname} ({fenum})"

def _bucket_midpoint(bucket: str) -> Optional[float]:
    try:
        lo, hi = str(bucket).split("_", 1)
        return (float(lo) + float(hi)) / 2.0
    except Exception:
        return None

def _red_green_ramp(t: float) -> tuple[float, float, float]:
    """
    t in [0, 1]: 0 = red (1,0,0), 1 = green (0,1,0)
    """
    if t <= 0:
        return (1.0, 0.0, 0.0)
    if t >= 1:
        return (0.0, 1.0, 0.0)
    return (1.0 - t, t, 0.0)

def _tth_bucket_color(bucket: str) -> tuple[float, float, float]:
    """
    Two-section coloring:
      0–30 min:  0=red → 30=green
      30–60 min: 30=red → 60=green
    """
    mid = _bucket_midpoint(bucket)
    if mid is None:
        return (0.6, 0.6, 0.6)  # neutral gray

    if 0 <= mid <= 30:
        # map 0 → 0.0 and 30 → 1.0
        t = mid / 30.0
        return (1.0 - t, t, 0.0)

    if 30 < mid <= 60:
        # reset ramp at 30 → red
        t = (mid - 30.0) / 30.0
        return (1.0 - t, t, 0.0)

    # fallback outside 0–60
    return (0.3, 0.3, 0.3)



def _bucket_sort_key(b: str) -> tuple:
    # Sort "10_15" by numeric lower bound; fall back to string
    try:
        lo = int(str(b).split("_", 1)[0])
        return (0, lo, str(b))
    except Exception:
        return (1, 0, str(b))

def _hours_sorted(bucket_to_series: dict[str, dict[str, float]]) -> list[int]:
    def hour_num(k: str) -> int:
        try:
            return int(str(k).split(" ", 1)[1])
        except Exception:
            return 0
    all_keys = {k for s in bucket_to_series.values() for k in s.keys()}
    return sorted({hour_num(k) for k in all_keys})

_TS_KEYS = ("ts", "timestamp", "time", "bucket", "start")

def _coerce_list(data: Any) -> List[Dict[str, Any]]:
    """Accept list[dict] or {'data': list[dict]} or fallback to []."""
    if data is None:
        return []
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        return data["data"]
    if isinstance(data, list):
        return data
    return []

def _pick_time_key(row: Dict[str, Any]) -> Optional[str]:
    for k in _TS_KEYS:
        if k in row:
            return k
    return None

def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        # Accept unix seconds or ms
        s = float(v)
        if s > 10_000_000_000:  # ms
            s = s / 1000.0
        try:
            return datetime.utcfromtimestamp(s)
        except Exception:
            return None
    if isinstance(v, str):
        try:
            v2 = v.replace("Z", "+00:00")
            return datetime.fromisoformat(v2)
        except Exception:
            return None
    return None

def _auto_y_keys(rows: List[Dict[str, Any]], exclude: Iterable[str]) -> List[str]:
    """Pick numeric columns to plot."""
    if not rows:
        return []
    ex = set(exclude)
    keys = set().union(*[r.keys() for r in rows]) - ex
    numeric = []
    for k in keys:
        # consider numeric if first non-None value is int/float
        val = next((r.get(k) for r in rows if r.get(k) is not None), None)
        if isinstance(val, (int, float)):
            numeric.append(k)
    return sorted(numeric)

def _save_current_fig_to_bytes(dpi: int = 160) -> bytes:
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return buf.getvalue()

async def _send_image(
    inter: discord.Interaction,
    img_bytes: bytes,
    title: str,
    *,
    ephemeral: bool = True,
    filename_slug: str = "chart",
):
    file = discord.File(io.BytesIO(img_bytes), filename=f"{filename_slug}.png")
    emb = discord.Embed(title=title, color=0x2f3136)
    emb.set_image(url=f"attachment://{filename_slug}.png")
    if inter.response.is_done():
        await inter.followup.send(embed=emb, file=file, ephemeral=ephemeral)
    else:
        await inter.response.send_message(embed=emb, file=file, ephemeral=ephemeral)

# -----------------------
# Renderers
# -----------------------

def _line_or_area_label(y_keys: List[str]) -> str:
    if not y_keys:
        return "Count"
    if len(y_keys) == 1:
        return y_keys[0]
    return "Count"

def _format_title_suffix(area: Optional[str]) -> str:
    return "global" if not area else area

def _pick_group_key(rows: List[Dict[str, Any]]) -> Optional[str]:
    """
    For 'grouped' data, try to detect a categorical key like 'metric', 'pokemon_id', 'form', 'label', etc.
    We avoid time + numeric columns.
    """
    if not rows:
        return None
    numeric_candidates = _auto_y_keys(rows, exclude=_TS_KEYS)
    time_key = _pick_time_key(rows[0]) or ""
    for candidate in ("metric", "pokemon_id", "form", "label", "group", "bucket", "tth_bucket"):
        if candidate in rows[0] and candidate not in numeric_candidates and candidate != time_key:
            return candidate
    # Fallback: find a non-numeric, non-time string column present
    for k in rows[0].keys():
        if k == time_key or k in numeric_candidates:
            continue
        val = rows[0].get(k)
        if isinstance(val, str):
            return k
    return None

def _pivot_grouped(
    rows: List[Dict[str, Any]],
    time_key: str,
    group_key: str
) -> Tuple[List[datetime], Dict[str, List[float]]]:
    """
    Convert rows with keys [time_key, group_key, value?] into series per group.
    We try to find the numeric value column; if multiple numeric columns exist, we choose 'count' or first numeric.
    """
    numeric_cols = _auto_y_keys(rows, exclude=(time_key, group_key))
    val_key = "count" if "count" in numeric_cols else (numeric_cols[0] if numeric_cols else None)
    # Build mapping time->group->value
    times: List[datetime] = []
    seen_times = {}
    for r in rows:
        t = _parse_ts(r.get(time_key))
        if not t:
            continue
        if t not in seen_times:
            seen_times[t] = []
            times.append(t)
        seen_times[t].append(r)
    times.sort()
    series: Dict[str, List[float]] = {}
    groups = {str(r.get(group_key)) for r in rows if r.get(group_key) is not None}
    for g in sorted(groups, key=_bucket_sort_key):
        series[g] = []
    for t in times:
        at_t = seen_times[t]
        index = {str(r.get(group_key)): r for r in at_t}
        for g in series.keys():
            v = index.get(g, {})
            y = v.get(val_key, 0.0) if val_key else 0.0
            try:
                series[g].append(float(y))
            except Exception:
                series[g].append(0.0)
    return times, series

# ---------- Public chart functions used by handlers ----------

async def send_pokemon_counterseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    interval: str,
    mode: str,
    title_prefix: str = "Pokémon • Counters",
) -> None:
    """
    Draws:
      - sum: simple line of the first numeric key (or 'count')
      - grouped: stacked area by detected group key
      - surged: line chart (same as sum)
    """
    rows = _coerce_list(payload)
    title = f"{title_prefix} • {interval} • {_format_title_suffix(area)}"

    if not rows:
        return await _send_image(inter, _blank_image("No data"), title)

    time_key = _pick_time_key(rows[0])
    if not time_key:
        return await _send_image(inter, _blank_image("No time axis"), title)

    xs = []
    for r in rows:
        dt = _parse_ts(r.get(time_key))
        if dt:
            xs.append(dt)
    if not xs:
        return await _send_image(inter, _blank_image("No timestamps"), title)

    plt.figure(figsize=(9.5, 4.6))
    if mode == "grouped":
        group_key = _pick_group_key(rows)
        if group_key:
            ts, by_group = _pivot_grouped(rows, time_key, group_key)
            # one stackplot call with all series to properly stack
            ys_list = list(by_group.values())
            labels = list(by_group.keys())
            plt.stackplot(ts, *ys_list, labels=labels)
            plt.legend(loc="upper left", fontsize=9, ncols=2)
            plt.xlabel("Time")
            plt.ylabel("Count")
            plt.title(title)
            img = _save_current_fig_to_bytes()
            return await _send_image(inter, img, title, filename_slug="pokemon_counters")
        # else fall through to sum

    # sum / surged → pick numeric y-keys
    y_keys = _auto_y_keys(rows, exclude=(time_key,))
    y_key = "count" if "count" in y_keys else (y_keys[0] if y_keys else None)

    ys, xs = [], []
    for r in rows:
        t = _parse_ts(r.get(time_key))
        if not t:
            continue
        v = r.get(y_key, 0.0) if y_key else 0.0
        try:
            ys.append(float(v))
            xs.append(t)
        except Exception:
            pass

    plt.plot(xs, ys)
    plt.xlabel("Time")
    plt.ylabel(_line_or_area_label([y_key] if y_key else []))
    plt.title(title)
    img = _save_current_fig_to_bytes()
    await _send_image(inter, img, title, filename_slug="pokemon_counters")

async def send_pokemon_timeseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    mode: str,
    title_prefix: str = "Pokémon • TimeSeries",
    selected_pokemon_id: Optional[int] = None,
    selected_form_id: Optional[int] = None,
) -> None:
    """
    SUM:
      Aggregate across areas when global; send a single "Totals: N" message
      and chart non-total metrics from the aggregated sums.
    GROUPED:
      One Top-15 chart per metric (totals, iv*, shiny, pvp_*...), aggregated when global.
    SURGED:
      Aggregate across areas when global; send a single "Totals (surged): N"
      and chart non-total metrics by hour from the aggregated series.
    """
    title = f"{title_prefix} • {_format_title_suffix(area)}"

    # helpers to recognize shape + normalize
    def is_multi_area(d: Any) -> bool:
        return isinstance(d, dict) and "data" not in d and any(
            isinstance(v, dict) and "data" in v for v in d.values()
        )

    def norm_sum(block: dict[str, Any]) -> dict[str, float]:
        data = block.get("data") or {}
        out = {}
        for k, v in data.items():
            if isinstance(v, (int, float)):
                out[str(k)] = float(v)
        return out

    def norm_grouped(block: dict[str, Any]) -> dict[str, dict[str, float]]:
        data = block.get("data") or {}
        out: dict[str, dict[str, float]] = {}
        for metric, inner in data.items():
            if not isinstance(inner, dict):
                continue
            out_metric: dict[str, float] = {}
            for pf, cnt in inner.items():
                try: out_metric[str(pf)] = float(cnt)
                except Exception: pass
            out[str(metric)] = out_metric
        return out

    def norm_surged(block: dict[str, Any]) -> dict[str, dict[str, float]]:
        data = block.get("data") or {}
        out: dict[str, dict[str, float]] = {}
        for metric, inner in data.items():
            if not isinstance(inner, dict):
                continue
            out_metric: dict[str, float] = {}
            for hr, cnt in inner.items():
                try: out_metric[str(hr)] = float(cnt)
                except Exception: pass
            out[str(metric)] = out_metric
        return out

    # ---------- SUM ----------
    if mode == "sum":
        agg: dict[str, float] = {}
        if is_multi_area(payload):
            # aggregate across all areas into one dict
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "sum":
                    continue
                m = norm_sum(block)
                for k, v in m.items():
                    agg[k] = agg.get(k, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "sum":
            agg = norm_sum(payload)
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        # totals message (single line)
        await inter.followup.send(f"**Totals:** **{int(agg.get('total', 0)):,}**", ephemeral=True)

        # If request was filtered to a specific pokemon/form, that's all we need
        if selected_pokemon_id is not None or selected_form_id is not None:
            return

        # chart remaining metrics (exclude total)
        rest_keys = [k for k in agg.keys() if k != "total"]
        if not rest_keys:
            return await _send_image(inter, _blank_image("No non-total metrics"), title)

        preferred = ["shiny", "iv100", "iv0", "pvp_little", "pvp_great", "pvp_ultra"]
        keys = [k for k in preferred if k in rest_keys] + [k for k in rest_keys if k not in preferred]
        vals = [agg.get(k, 0.0) for k in keys]
        colors = [_metric_color(k) for k in keys]

        plt.figure(figsize=(9.8, 5.0))
        bars = plt.bar(keys, vals, color=colors)
        plt.xticks(rotation=30, ha="right")
        plt.ylabel("Count")
        plt.title(f"{title} • sum (non-total)")
        _annotate_bars(plt.gca(), bars, vals)
        img = _save_current_fig_to_bytes()
        return await _send_image(inter, img, f"{title} • sum", filename_slug="pokemon_timeseries_sum")

    # ---------- GROUPED ----------
    elif mode == "grouped":
        merged_by_metric: dict[str, dict[str, float]] = {}
        if is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "grouped":
                    continue
                ng = norm_grouped(block)
                for metric, mp in ng.items():
                    acc = merged_by_metric.setdefault(metric, {})
                    for pf, v in mp.items():
                        acc[pf] = acc.get(pf, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "grouped":
            merged_by_metric = norm_grouped(payload)
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        if not merged_by_metric:
            return await _send_image(inter, _blank_image("No data"), title)

        for metric, mp in merged_by_metric.items():
            if not mp:
                continue
            top = sorted(mp.items(), key=lambda kv: kv[1], reverse=True)[:15]
            labels = [_pidform_label(k) for k, _ in top]
            values = [v for _, v in top]

            plt.figure(figsize=(10.5, 6.5))
            y_pos = list(range(len(labels)))
            color = _metric_color(metric)
            plt.barh(y_pos, values, color=color)
            plt.yticks(y_pos, labels)
            plt.gca().invert_yaxis()
            plt.xlabel("Count")
            plt.title(f"{title} • grouped • {metric} (top {len(labels)})")
            for y, v in zip(y_pos, values):
                plt.text(v, y, f"  {int(v):,}", va="center", ha="left", fontsize=8)

            img = _save_current_fig_to_bytes()
            await _send_image(
                inter,
                img,
                f"{title} • grouped • {metric}",
                filename_slug=f"pokemon_timeseries_grouped_{metric}"
            )
        return

    # ---------- SURGED ----------
    elif mode == "surged":
        merged: dict[str, dict[str, float]] = {}

        # aggregate across areas if global
        if is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "surged":
                    continue
                ns = norm_surged(block)
                for metric, inner in ns.items():
                    acc = merged.setdefault(metric, {})
                    for hr, v in inner.items():
                        acc[hr] = acc.get(hr, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "surged":
            merged = norm_surged(payload)
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        if not merged:
            return await _send_image(inter, _blank_image("No data"), title)

        # Totals (single number) + per-hour lines
        totals_series = merged.get("total", {})
        total_count = int(sum(totals_series.values()))
        await inter.followup.send(f"**Totals (surged):** **{total_count:,}**", ephemeral=True)

        # Hour ordering and pretty “Hour X - value” lists
        def hour_num(k: str) -> int:
            try: return int(str(k).split(" ", 1)[1])
            except Exception: return 0

        x_keys = sorted(totals_series.keys() | set().union(*[d.keys() for d in merged.values() if isinstance(d, dict)]), key=hour_num)
        if x_keys:
            # 1) Totals by hour
            lines = [f"**Totals by hour:**"]
            for k in x_keys:
                lines.append(f"• Hour {hour_num(k)} — {_fmt_compact(totals_series.get(k, 0))}")
            await inter.followup.send("\n".join(lines), ephemeral=True)

            # 2) Shiny by hour (if shiny exists)
            shiny_series = merged.get("shiny", {})
            if shiny_series:
                lines = [f"**Shiny by hour:**"]
                for k in x_keys:
                    lines.append(f"• Hour {hour_num(k)} — {_fmt_compact(shiny_series.get(k, 0))}")
                await inter.followup.send("\n".join(lines), ephemeral=True)

        # Build chart of non-total metrics (clustered bars per hour)
        all_hours = set()
        for d in merged.values():
            all_hours.update(d.keys())
        x_keys = sorted(all_hours, key=hour_num)
        hours = [hour_num(k) for k in x_keys]
        idx = list(range(len(hours)))

        metrics_all = [m for m in merged.keys() if m not in ("total", "shiny")]
        if not metrics_all:
            return await _send_image(inter, _blank_image("No non-total metrics"), title)

        preferred = ["shiny", "iv100", "iv0", "pvp_little", "pvp_great", "pvp_ultra"]
        metrics = [m for m in preferred if m in metrics_all] + [m for m in metrics_all if m not in preferred]
        metrics = metrics[:10]

        plt.figure(figsize=(10.8, 5.6))
        ax = plt.gca()
        n_series = max(1, len(metrics))
        width = 0.8 / n_series
        for i, metric in enumerate(metrics):
            series = merged[metric]
            y_vals = [float(series.get(k, 0.0)) for k in x_keys]
            offsets = [x - 0.4 + i * width + width / 2 for x in idx]
            bars = plt.bar(offsets, y_vals, width=width, label=metric, color=_metric_color(metric))
            _annotate_bars(ax, bars, y_vals)

        plt.xticks(idx, [str(h) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Count")
        plt.title(f"{title} • surged (non-total)")
        if len(metrics) <= 10:
            plt.legend(fontsize=8, ncols=3, loc="upper left")
        img = _save_current_fig_to_bytes()
        return await _send_image(inter, img, f"{title} • surged", filename_slug="pokemon_timeseries_surged")

    # ---------- fallback ----------
    else:
        return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title)


async def send_pokemon_tth_timeseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    mode: str,
    title_prefix: str = "Pokémon • TimeSeries • TTH",
) -> None:
    """
    Supports payloads:
      1) {"mode": "...", "data": { "<bucket>": { "<unix_ts>": count, ... }, ... }}
      2) {"mode": "surged", "data": { "<bucket>": { "hour 13": count, ... }, ... }}
      3) { "<AreaName>": {"mode": "...", "data": {...}}, ... }  (aggregated across many areas)
    """
    title = f"{title_prefix} • {_format_title_suffix(area)}"

    def _is_multi_area(d: Any) -> bool:
        return isinstance(d, dict) and "data" not in d and any(
            isinstance(v, dict) and "data" in v for v in d.values()
        )

    def _normalize_single_area(d: Dict[str, Any]) -> Tuple[str, Dict[str, Dict[str, float]]]:
        m = str(d.get("mode", mode or "sum")).lower()
        data = d.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        norm: Dict[str, Dict[str, float]] = {}
        for bucket, series in data.items():
            if not isinstance(series, dict):
                # sum-mode might be flat {"15_20": 3361, ...}
                if isinstance(series, (int, float)):
                    norm.setdefault(str(bucket), {})["__total__"] = float(series)
                continue
            inner: Dict[str, float] = {}
            for k, v in series.items():
                try:
                    inner[str(k)] = float(v)
                except Exception:
                    pass
            norm[str(bucket)] = inner
        return m, norm

    # Fold into (final_mode, {bucket: {time_key: value}})
    final_mode = str(mode or "sum").lower()
    bucket_to_series: Dict[str, Dict[str, float]] = {}

    if _is_multi_area(payload):
        for _, block in payload.items():
            if not isinstance(block, dict) or "data" not in block:
                continue
            m, norm = _normalize_single_area(block)
            final_mode = m  # they should match, but take last seen
            for bucket, series in norm.items():
                acc = bucket_to_series.setdefault(bucket, {})
                for tkey, val in series.items():
                    acc[tkey] = acc.get(tkey, 0.0) + float(val)
    elif isinstance(payload, dict) and "data" in payload:
        final_mode, bucket_to_series = _normalize_single_area(payload)
    else:
        return await _send_image(inter, _blank_image("Unsupported payload"), title)

    if not bucket_to_series:
        return await _send_image(inter, _blank_image("No data"), title)

    # Detect flavor of time keys
    def _is_hour_label(s: str) -> bool:
        s = str(s).lower()
        return s.startswith("hour ") and s[5:].strip().isdigit()

    all_keys = set()
    for series in bucket_to_series.values():
        all_keys.update(series.keys())

    has_totals_only = all_keys == {"__total__"} or all(k == "__total__" for k in all_keys)
    is_hourly = (not has_totals_only) and all(_is_hour_label(k) for k in all_keys)
    is_unix = (not has_totals_only and not is_hourly) and all(str(k).isdigit() for k in all_keys)

    plt.figure(figsize=(9.5, 4.6))

    if has_totals_only or final_mode == "sum":
        # Bar chart of bucket totals
        buckets = sorted(bucket_to_series.keys(), key=_bucket_sort_key)
        totals = [
            float(
                bucket_to_series[bucket].get("__total__", 0.0)
                or sum(bucket_to_series[bucket].values())
            )
            for bucket in buckets
        ]
        colors = [_tth_bucket_color(b) for b in buckets]
        plt.bar(buckets, totals, color=colors)
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("Count")
        plt.title(title)
        img = _save_current_fig_to_bytes()
        return await _send_image(inter, img, title, filename_slug="pokemon_tth")

    if is_hourly:
        # Ordered hour axis
        def hour_num(k: str) -> int:
            try:
                return int(str(k).split(" ", 1)[1])
            except Exception:
                return 0

        x_keys = sorted(list(all_keys), key=hour_num)
        hours = [hour_num(k) for k in x_keys]
        idx = list(range(len(hours)))
        buckets = sorted(bucket_to_series.keys(), key=_bucket_sort_key)

        if final_mode == "grouped":
            # Stacked area by TTH bucket
            Y = []
            labels = []
            colors = []
            for bucket in buckets:
                series = bucket_to_series[bucket]
                ys = [float(series.get(k, 0.0)) for k in x_keys]
                Y.append(ys)
                labels.append(bucket)
                colors.append(_tth_bucket_color(bucket))
            plt.stackplot(hours, *Y, labels=labels, colors=colors)
            plt.legend(loc="upper left", fontsize=9, ncols=2)
        else:
            # SURGED → grouped bars per hour (cluster = buckets)
            n_b = max(1, len(buckets))
            width = 0.8 / n_b
            for i, bucket in enumerate(buckets):
                series = bucket_to_series[bucket]
                y_vals = [float(series.get(k, 0.0)) for k in x_keys]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                plt.bar(offsets, y_vals, width=width, label=bucket, color=_tth_bucket_color(bucket))

            plt.xticks(idx, [str(h) for h in hours], rotation=0)
            # keep legend manageable
            if len(buckets) <= 12:
                plt.legend(fontsize=8, ncols=2, loc="upper left")

        plt.xlabel("Hour")
        plt.ylabel("Count")
        plt.title(title)
        img = _save_current_fig_to_bytes()
        return await _send_image(inter, img, title, filename_slug="pokemon_tth")

    if is_unix:
        ts_sorted = sorted({int(k) for k in all_keys})
        TS = [datetime.utcfromtimestamp(t if t < 10_000_000_000 else t / 1000.0) for t in ts_sorted]

        if final_mode == "grouped":
            buckets = sorted(bucket_to_series.keys(), key=_bucket_sort_key)
            Y = []
            labels = []
            colors = []
            for bucket in buckets:
                series = bucket_to_series[bucket]
                ys = [float(series.get(str(t), 0.0)) for t in ts_sorted]
                Y.append(ys)
                labels.append(bucket)
                colors.append(_tth_bucket_color(bucket))

            plt.stackplot(TS, *Y, labels=labels, colors=colors)
            plt.legend(loc="upper left", fontsize=9, ncols=2)
        else:
            sums = [
                sum(float(bucket_to_series[b].get(str(t), 0.0)) for b in bucket_to_series.keys())
                for t in ts_sorted
            ]
            plt.plot(TS, sums)

        plt.xlabel("Time")
        plt.ylabel("Count")
        plt.title(title)
        img = _save_current_fig_to_bytes()
        return await _send_image(inter, img, title, filename_slug="pokemon_tth")

    # Fallback
    return await _send_image(inter, _blank_image("Unrecognized time keys"), title)

# -----------------------
# Blank placeholder image
# -----------------------

def _blank_image(text: str = "No data") -> bytes:
    plt.figure(figsize=(8, 2.6))
    plt.axis("off")
    plt.text(0.5, 0.5, text, ha="center", va="center", fontsize=14)
    return _save_current_fig_to_bytes(dpi=140)
