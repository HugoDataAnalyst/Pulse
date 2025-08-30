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
    """Compact number formatting (k, M, B) for ephem. messages."""
    try:
        n = float(n)
    except Exception:
        return str(n)

    def fmt(val: float, suffix: str) -> str:
        # one decimal, strip trailing .0
        base = f"{val:.1f}".rstrip("0").rstrip(".")
        return f"{base}{suffix}"

    if n >= 1_000_000_000:
        return fmt(n / 1_000_000_000, "B")
    elif n >= 1_000_000:
        return fmt(n / 1_000_000, "M")
    elif n >= 1_000:
        return fmt(n / 1_000, "k")
    else:
        return str(int(n)) if n.is_integer() else f"{n:.0f}"

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

def _annotate_bars_h(ax, bars, values):
    """Annotate horizontal bars at the bar tip (to the right)."""
    for rect, v in zip(bars, values):
        try:
            w = rect.get_width()
            if w <= 0:
                continue
            y = rect.get_y() + rect.get_height() / 2.0
            ax.text(
                w, y,
                f"  {_fmt_compact(v)}",
                va="center",
                ha="left",
                fontsize=8,
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

# cache for weather name<->id maps
_WEATHER_REV: dict[str, str] | None = None   # "1" -> "CLEAR"
_WEATHER_FWD: dict[str, str] | None = None   # "CLEAR" -> "1"

def _load_weather_maps() -> tuple[dict[str, str], dict[str, str]]:
    """
    Returns (WEATHER_REV, WEATHER_FWD):
      REV: {"1": "CLEAR", "2": "RAINY", ...}
      FWD: {"CLEAR": "1", "RAINY": "2", ...}
    """
    global _WEATHER_REV, _WEATHER_FWD
    if _WEATHER_REV is not None and _WEATHER_FWD is not None:
        return _WEATHER_REV, _WEATHER_FWD

    # same candidate list you already use for id_to_name.json
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "stats", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "id_to_name.json"),
    ]
    weather_rev, weather_fwd = {}, {}
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            w = data.get("WEATHER") or {}
            # file is name -> id; build both directions
            weather_fwd = {str(name): str(wid) for name, wid in w.items()}
            weather_rev = {str(wid): str(name) for name, wid in w.items()}
            break
        except Exception:
            continue

    _WEATHER_REV, _WEATHER_FWD = weather_rev, weather_fwd
    return weather_rev, weather_fwd

def _weather_label(metric_key: str) -> str:
    """Turn '1' into 'CLEAR' (falls back to the original key)."""
    rev, _ = _load_weather_maps()
    return rev.get(str(metric_key), str(metric_key))

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

def _format_title_suffix(area: Optional[str]) -> str:
    return "global" if not area else area


# ---------- Public chart functions used by handlers ----------

async def send_pokemon_counterseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    interval: str,
    mode: str,
    counter_type: str,           # "totals" | "tth" | "weather"
    metric: Optional[str] = None,
    title_prefix: str = "Pokémon • Counters",
    selected_pokemon_id: Optional[int] = None,
    selected_form_id: Optional[int] = None,
) -> None:
    """Counters visuals aligned with TimeSeries behavior."""

    # ---------- TTH COUNTERS ----------
    if counter_type.lower() == "tth":
        return await send_pokemon_tth_timeseries_chart(
            inter,
            payload,
            area=area,
            mode=mode,
            title_prefix=f"{title_prefix} • TTH",
        )

    title = f"{title_prefix} • {counter_type} • {interval} • {_format_title_suffix(area)}"

    def is_multi_area(d: Any) -> bool:
        return isinstance(d, dict) and "data" not in d and any(
            isinstance(v, dict) and "data" in v for v in d.values()
        )

    # ---------- TOTALS ----------
    if counter_type.lower() == "totals":
        def norm_sum(block: dict[str, Any]) -> dict[str, float]:
            data = block.get("data") or {}
            out = {}
            for k, v in data.items():
                if isinstance(v, (int, float)):
                    out[str(k)] = float(v)
            return out

        def norm_grouped(block: dict[str, Any]) -> dict[str, dict[str, float]]:
            """
            Return {metric -> { 'pid:form' -> count }}.
            Supports:
            A) nested: {"data": { "total": {"821:0": 10, ...}, "shiny": {...}, ... }}
            B) flattened: {"data": { "821:0:total": 10, "821:0:shiny": 2, ... }}
            """
            data = block.get("data") or {}
            out: dict[str, dict[str, float]] = {}

            # Detect flattened keys quickly (has at least one "a:b:c" key)
            flattened = any(
                isinstance(k, str) and k.count(":") >= 2 and isinstance(v, (int, float))
                for k, v in data.items()
            )

            if flattened:
                # k = "pid:form:metric" (sometimes more colons, take last segment as metric)
                for k, cnt in data.items():
                    if not isinstance(k, str) or not isinstance(cnt, (int, float)):
                        continue
                    parts = k.split(":")
                    if len(parts) < 3:
                        continue
                    metric_key = parts[-1]
                    pf_key = ":".join(parts[:-1])  # re-join pid:form (and any middle parts if present)
                    acc = out.setdefault(metric_key, {})
                    acc[pf_key] = acc.get(pf_key, 0.0) + float(cnt)
                return out

            # nested metric -> { pid:form -> count }
            for metric_key, inner in data.items():
                if not isinstance(inner, dict):
                    continue
                m: dict[str, float] = {}
                for pf, cnt in inner.items():
                    try:
                        m[str(pf)] = float(cnt)
                    except Exception:
                        pass
                out[str(metric_key)] = m

            return out

        def norm_surged(block: dict[str, Any]) -> dict[str, dict[str, float]]:
            data = block.get("data") or {}
            out: dict[str, dict[str, float]] = {}
            for metric_key, inner in data.items():
                if not isinstance(inner, dict):
                    continue
                out_metric: dict[str, float] = {}
                for hr, cnt in inner.items():
                    try:
                        out_metric[str(hr)] = float(cnt)
                    except Exception:
                        pass
                out[str(metric_key)] = out_metric
            return out

        # --- SUM ---
        if mode == "sum":
            agg: dict[str, float] = {}
            if is_multi_area(payload):
                for block in payload.values():
                    if not isinstance(block, dict) or block.get("mode") != "sum":
                        continue
                    for m, v in norm_sum(block).items():
                        agg[m] = agg.get(m, 0.0) + v
            elif isinstance(payload, dict) and payload.get("mode") == "sum":
                agg = norm_sum(payload)
            else:
                return await _send_image(inter, _blank_image("Unsupported payload"), title)

            # Selected mon/form → short message (unchanged)
            if selected_pokemon_id is not None or selected_form_id is not None:
                total = int(agg.get("total", 0))
                msg = f"Found **{total}** spawns"
                if selected_pokemon_id is not None:
                    msg += f" for **#{selected_pokemon_id}**"
                if selected_form_id is not None:
                    msg += f" (form {selected_form_id})"
                msg += "."
                return await inter.followup.send(msg, ephemeral=True)

            if not agg:
                return await _send_image(inter, _blank_image("No data"), title)

            # 1) Totals + Shiny as messages
            total_val = int(agg.get("total", 0))
            shiny_val = int(agg.get("shiny", 0))
            await inter.followup.send(f"**Totals:** **{_fmt_compact(total_val)}**", ephemeral=True)
            if shiny_val:
                await inter.followup.send(f"**Shiny:** **{_fmt_compact(shiny_val)}**", ephemeral=True)

            # 2) Bar chart for remaining metrics (exclude 'total' and 'shiny')
            metrics = [k for k in agg.keys() if k not in ("total", "shiny")]
            if not metrics:
                # Nothing else to visualize
                return await _send_image(inter, _blank_image("No non-total metrics"), f"{title} • sum")

            preferred = ["iv100", "iv0", "pvp_little", "pvp_great", "pvp_ultra"]
            metrics = [m for m in preferred if m in metrics] + [m for m in sorted(metrics) if m not in preferred]
            vals = [agg.get(m, 0.0) for m in metrics]
            colors = [_metric_color(m) for m in metrics]

            plt.figure(figsize=(9.8, 4.2))
            ax = plt.gca()
            bars = plt.bar(metrics, vals, color=colors)
            _annotate_bars(ax, bars, vals)
            plt.xticks(rotation=25, ha="right")
            plt.ylabel("Count")
            plt.title(f"{title} • sum (excluding total & shiny)")
            img = _save_current_fig_to_bytes()
            return await _send_image(inter, img, f"{title} • sum", filename_slug="pokemon_counters_sum")

        # --- GROUPED ---
        elif mode == "grouped":
            # Build per-metric maps (pid:form -> count), aggregated if global
            per_metric: dict[str, dict[str, float]] = {}
            if is_multi_area(payload):
                for block in payload.values():
                    if not isinstance(block, dict) or block.get("mode") != "grouped":
                        continue
                    ng = norm_grouped(block)
                    for metric_key, mapping in ng.items():
                        acc = per_metric.setdefault(metric_key, {})
                        for pf, cnt in mapping.items():
                            acc[pf] = acc.get(pf, 0.0) + cnt
            elif isinstance(payload, dict) and payload.get("mode") == "grouped":
                per_metric = norm_grouped(payload)
            else:
                return await _send_image(inter, _blank_image("Unsupported payload"), title)

            if not per_metric:
                return await _send_image(inter, _blank_image("No data"), title)

            # Selected mon/form → short message (sum counts inside 'total')
            if selected_pokemon_id is not None or selected_form_id is not None:
                merged_total = per_metric.get("total", {})
                def _match(pf: str) -> bool:
                    try:
                        pid_s, form_s = pf.split(":", 1)
                    except ValueError:
                        return False
                    ok = True
                    if selected_pokemon_id is not None:
                        ok = ok and (pid_s == str(selected_pokemon_id))
                    if selected_form_id is not None:
                        ok = ok and (form_s == str(selected_form_id))
                    return ok
                count = int(sum(v for k, v in merged_total.items() if _match(k)))
                msg = f"Found **{count}** spawns"
                if selected_pokemon_id is not None:
                    msg += f" for **#{selected_pokemon_id}**"
                if selected_form_id is not None:
                    msg += f" (form {selected_form_id})"
                msg += "."
                return await inter.followup.send(msg, ephemeral=True)

            # 1) Totals + Shiny messages (sum over their maps if present)
            total_sum = int(sum(per_metric.get("total", {}).values()))
            await inter.followup.send(f"**Totals:** **{_fmt_compact(total_sum)}**", ephemeral=True)
            shiny_sum = int(sum(per_metric.get("shiny", {}).values()))
            if shiny_sum:
                await inter.followup.send(f"**Shiny:** **{_fmt_compact(shiny_sum)}**", ephemeral=True)

            # 2) For each metric except total & shiny, plot Top-15 pid:form
            metrics_to_plot = [m for m in per_metric.keys() if m not in ("total", "shiny")]
            preferred = ["iv100", "iv0", "pvp_little", "pvp_great", "pvp_ultra"]
            metrics_to_plot = [m for m in preferred if m in metrics_to_plot] + \
                            [m for m in sorted(metrics_to_plot) if m not in preferred]

            if not metrics_to_plot:
                return  # nothing non-total/non-shiny to chart

            N = 15
            for metric_name in metrics_to_plot:
                mapping = per_metric.get(metric_name, {})
                if not mapping:
                    continue
                top = sorted(mapping.items(), key=lambda kv: kv[1], reverse=True)[:N]
                labels = [_pidform_label(k) for k, _ in top]
                values = [v for _, v in top]

                plt.figure(figsize=(10.5, 6.2))
                ax = plt.gca()
                y_pos = list(range(len(labels)))
                bars = plt.barh(y_pos, values, color=_metric_color(metric_name))
                plt.yticks(y_pos, labels)
                plt.gca().invert_yaxis()
                _annotate_bars_h(ax, bars, values)
                plt.xlabel("Count")
                plt.title(f"{title} • grouped • {metric_name} (top {len(labels)})")
                img = _save_current_fig_to_bytes()
                await _send_image(
                    inter, img,
                    f"{title} • grouped • {metric_name}",
                    filename_slug=f"pokemon_counters_grouped_{metric_name}"
                )

            return

        # --- SURGED ---
        elif mode == "surged":
            merged: dict[str, dict[str, float]] = {}
            if is_multi_area(payload):
                for block in payload.values():
                    if not isinstance(block, dict) or block.get("mode") != "surged":
                        continue
                    ns = norm_surged(block)
                    for metric_key, inner in ns.items():
                        acc = merged.setdefault(metric_key, {})
                        for hr, v in inner.items():
                            acc[hr] = acc.get(hr, 0.0) + v
            elif isinstance(payload, dict) and payload.get("mode") == "surged":
                merged = norm_surged(payload)
            else:
                return await _send_image(inter, _blank_image("Unsupported payload"), title)

            if not merged:
                return await _send_image(inter, _blank_image("No data"), title)

            # Totals + hourly lists
            totals_series = merged.get("total", {})
            total_count = int(sum(totals_series.values()))
            await inter.followup.send(f"**Totals (surged):** **{_fmt_compact(total_count)}**", ephemeral=True)

            def hour_num(k: str) -> int:
                try: return int(str(k).split(" ", 1)[1])
                except Exception: return 0

            all_hours_keys = set().union(*[d.keys() for d in merged.values() if isinstance(d, dict)]) or totals_series.keys()
            x_keys = sorted(all_hours_keys, key=hour_num)

            if x_keys:
                lines = ["**Totals by hour:**"]
                for k in x_keys:
                    lines.append(f"• Hour {hour_num(k)} — {_fmt_compact(totals_series.get(k, 0))}")
                await inter.followup.send("\n".join(lines), ephemeral=True)

                shiny_series = merged.get("shiny", {})
                if shiny_series:
                    lines = ["**Shiny by hour:**"]
                    for k in x_keys:
                        lines.append(f"• Hour {hour_num(k)} — {_fmt_compact(shiny_series.get(k, 0))}")
                    await inter.followup.send("\n".join(lines), ephemeral=True)

            # Chart for non-total & non-shiny metrics
            metrics_all = [m for m in merged.keys() if m not in ("total", "shiny")]
            if not metrics_all:
                return await _send_image(inter, _blank_image("No non-total metrics"), title)

            hours = [hour_num(k) for k in x_keys]
            idx = list(range(len(hours)))
            preferred = ["iv100", "iv0", "pvp_little", "pvp_great", "pvp_ultra"]
            metrics = [m for m in preferred if m in metrics_all] + [m for m in metrics_all if m not in preferred]
            metrics = metrics[:10]

            plt.figure(figsize=(10.8, 5.6))
            ax = plt.gca()
            n_series = max(1, len(metrics))
            width = 0.8 / n_series
            for i, metric_name in enumerate(metrics):
                series = merged[metric_name]
                y_vals = [float(series.get(k, 0.0)) for k in x_keys]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offsets, y_vals, width=width, label=metric_name, color=_metric_color(metric_name))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(h) for h in hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged (excluding total & shiny)")
            if len(metrics) <= 10:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            return await _send_image(inter, img, f"{title} • surged", filename_slug="pokemon_counters_surged")

        else:
            return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title)

    # ---------- WEATHER (monthly) ----------
    if counter_type.lower() == "weather":
        # SUM: {metric -> {threshold -> count}}
        # GROUPED: {(YYYYMM, metric) -> {threshold -> count}}
        def norm_sum(block: dict[str, Any]) -> dict[str, dict[str, float]]:
            data = block.get("data") or {}
            out: dict[str, dict[str, float]] = {}
            for metric_key, inner in data.items():
                if not isinstance(inner, dict):
                    continue
                th_map: dict[str, float] = {}
                for th, cnt in inner.items():
                    try:
                        th_map[str(th)] = float(cnt)
                    except Exception:
                        pass
                out[str(metric_key)] = th_map
            return out

        def norm_grouped(block: dict[str, Any]) -> dict[tuple[str, str], dict[str, float]]:
            data = block.get("data") or {}
            out: dict[tuple[str, str], dict[str, float]] = {}
            for ym_metric, inner in data.items():
                if not isinstance(inner, dict):
                    continue
                try:
                    ym, metric_key = str(ym_metric).split(":", 1)
                except ValueError:
                    continue
                th_map: dict[str, float] = {}
                for th, cnt in inner.items():
                    try:
                        th_map[str(th)] = float(cnt)
                    except Exception:
                        pass
                out[(ym, str(metric_key))] = th_map
            return out

        # --- SUM ---
        if mode == "sum":
            agg: dict[str, dict[str, float]] = {}
            if is_multi_area(payload):
                for block in payload.values():
                    if not isinstance(block, dict) or block.get("mode") != "sum":
                        continue
                    ns = norm_sum(block)
                    for m, th_map in ns.items():
                        acc = agg.setdefault(m, {})
                        for th, v in th_map.items():
                            acc[th] = acc.get(th, 0.0) + v
            elif isinstance(payload, dict) and payload.get("mode") == "sum":
                agg = norm_sum(payload)
            else:
                return await _send_image(inter, _blank_image("Unsupported payload"), title)

            if not agg:
                return await _send_image(inter, _blank_image("No data"), title)

            # decide which metrics to show
            metrics = sorted(agg.keys(), key=lambda s: int(s) if str(s).isdigit() else 999)

            # if the handler passed a metric filter, keep numeric behavior;
            # (your handlers already pass numbers like "1")
            if metric is not None:
                metric_id = str(metric)
                # also allow name filters like "CLEAR" if you ever pass them:
                _, wfwd = _load_weather_maps()
                metric_id = wfwd.get(str(metric), metric_id)
                if metric_id in agg:
                    metrics = [metric_id]
                else:
                    metrics = []

            # message totals with friendly names
            lines = ["**Weather totals:**"]
            for m in metrics:
                lines.append(f"• {_weather_label(m)}: **{_fmt_compact(int(sum(agg[m].values())))}**")
            await inter.followup.send("\n".join(lines), ephemeral=True)

            # stacked bars (thresholds stack within each metric) with friendly x labels
            plt.figure(figsize=(10.5, 5.6))
            ax = plt.gca()
            all_th = set().union(*[agg[m].keys() for m in metrics]) if metrics else set()
            th_sorted = sorted(all_th, key=lambda s: int(s) if str(s).isdigit() else 999)
            bottoms = [0.0] * len(metrics)

            x_labels = [_weather_label(m) for m in metrics]
            for th in th_sorted:
                vals = [agg[m].get(th, 0.0) for m in metrics]
                bars = plt.bar(x_labels, vals, bottom=bottoms, label=th)
                _annotate_bars(ax, bars, [b + v for b, v in zip(bottoms, vals)])
                bottoms = [b + v for b, v in zip(bottoms, vals)]

            plt.legend(title="Threshold", fontsize=8, ncols=3, loc="upper left")
            plt.ylabel("Count")
            plt.title(f"{title} • sum (stacked by threshold)")
            img = _save_current_fig_to_bytes()
            return await _send_image(inter, img, f"{title} • weather_sum", filename_slug="pokemon_counters_weather_sum")


        # --- GROUPED ---
        elif mode == "grouped":
            agg: dict[tuple[str, str], dict[str, float]] = {}
            if is_multi_area(payload):
                for block in payload.values():
                    if not isinstance(block, dict) or block.get("mode") != "grouped":
                        continue
                    ng = norm_grouped(block)
                    for key, th_map in ng.items():
                        acc = agg.setdefault(key, {})
                        for th, v in th_map.items():
                            acc[th] = acc.get(th, 0.0) + v
            elif isinstance(payload, dict) and payload.get("mode") == "grouped":
                agg = norm_grouped(payload)
            else:
                return await _send_image(inter, _blank_image("Unsupported payload"), title)

            if not agg:
                return await _send_image(inter, _blank_image("No data"), title)

            month_keys = sorted({ym for (ym, _m) in agg.keys()})

            metric_filter = None
            if metric is not None:
                # allow numeric or name input
                _, wfwd = _load_weather_maps()
                metric_filter = wfwd.get(str(metric), str(metric))

            metrics = sorted(
                {m for (_ym, m) in agg.keys() if (metric_filter is None or m == metric_filter)},
                key=lambda s: int(s) if s.isdigit() else 999
            )

            for m in metrics:
                plt.figure(figsize=(10.5, 5.6))
                ax = plt.gca()
                th_all = set().union(*[agg.get((ym, m), {}).keys() for ym in month_keys]) if month_keys else set()
                th_sorted = sorted(th_all, key=lambda s: int(s) if s.isdigit() else 999)
                bottoms = [0.0] * len(month_keys)

                for th in th_sorted:
                    vals = [agg.get((ym, m), {}).get(th, 0.0) for ym in month_keys]
                    bars = plt.bar(month_keys, vals, bottom=bottoms, label=th)
                    _annotate_bars(ax, bars, [b + v for b, v in zip(bottoms, vals)])
                    bottoms = [b + v for b, v in zip(bottoms, vals)]

                plt.legend(title="Threshold", fontsize=8, ncols=3, loc="upper left")
                plt.ylabel("Count")
                plt.title(f"{title_prefix} • weather • grouped • {_weather_label(m)} • {_format_title_suffix(area)}")
                img = _save_current_fig_to_bytes()
                await _send_image(
                    inter, img,
                    f"{title_prefix} • weather • grouped • {_weather_label(m)} • {_format_title_suffix(area)}",
                    filename_slug=f"pokemon_counters_weather_grouped_m{m}"
                )

            return  # multiple images posted

        else:
            return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}' for weather"), title)

    # ---------- FALLBACK ----------
    return await _send_image(inter, _blank_image("Unsupported counter type"), title)

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
        """
        Returns (mode, bucket_to_series) where:
        bucket_to_series = { "<bucket>": { "<time-key>": float } }

        Supports:
        - SUM/GROUPED with bucket->series mapping already
        - SURGED with EITHER:
            (i) bucket -> {"hour 15": v, ...}
            (ii) hour   -> { bucket: v, ... }   <-- invert to bucket->hour
        """
        m = str(d.get("mode", mode or "sum")).lower()
        data = d.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        # Helper: hour label detection (accept "hour 15" OR "15")
        def _is_hour_label(s: str) -> bool:
            s = str(s).lower().strip()
            return (s.startswith("hour ") and s[5:].strip().isdigit()) or s.isdigit()

        # Check if we have HOUR-FIRST (keys look like hours, values are {bucket:count})
        hour_first = (
            m == "surged"
            and all(_is_hour_label(k) and isinstance(v, dict) for k, v in data.items())
            and any(isinstance(v, dict) for v in data.values())
        )

        norm: Dict[str, Dict[str, float]] = {}

        if hour_first:
            # invert: hour -> {bucket: v}  ==>  bucket -> { "hour X": v }
            for hr, bucket_map in data.items():
                if not isinstance(bucket_map, dict):
                    continue
                # normalize hour key to "hour N" (string) for consistency
                hr_s = str(hr).strip()
                if hr_s.isdigit():
                    hour_key = f"hour {int(hr_s)}"
                elif hr_s.lower().startswith("hour "):
                    hour_key = f"hour {hr_s.split(' ', 1)[1].strip()}"
                else:
                    hour_key = hr_s  # fallback

                for bucket, v in bucket_map.items():
                    try:
                        acc = norm.setdefault(str(bucket), {})
                        acc[hour_key] = acc.get(hour_key, 0.0) + float(v)
                    except Exception:
                        pass
            return m, norm

        # Otherwise behave as before: bucket -> series (totals/unix/hour labels)
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
            s = str(k).lower().strip()
            if s.startswith("hour "):
                s = s[5:].strip()
            try:
                return int(s)
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
