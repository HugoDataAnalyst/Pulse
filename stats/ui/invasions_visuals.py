from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import os
import json
import io
from datetime import datetime
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import discord

# Shared helpers
from stats.psyduckv2.utils.visual_helpers import (
    _fmt_compact,
    _annotate_bars,
    _annotate_bars_h,
    _save_current_fig_to_bytes,
    _send_image,
    _format_title_suffix,
)

# ---------- local (invasion-specific) helpers ----------

_INV_DISPLAY_REV: dict[str, str] | None = None      # "1" -> "GRUNT", ...
_INV_CHARACTER_REV: dict[str, str] | None = None    # "10" -> "DARK_GRUNT_FEMALE", ...

def _load_invasion_maps() -> tuple[dict[str, str], dict[str, str]]:
    """
    Loads InvasionDisplayType and InvasionCharacterGrunt from id_to_name.json
    and returns reversed maps:
      display_rev:   {"1": "GRUNT", "2": "LEADER", ...}
      character_rev: {"10": "DARK_GRUNT_FEMALE", "44": "GIOVANNI", ...}
    """
    global _INV_DISPLAY_REV, _INV_CHARACTER_REV
    if _INV_DISPLAY_REV is not None and _INV_CHARACTER_REV is not None:
        return _INV_DISPLAY_REV, _INV_CHARACTER_REV

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "stats", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "id_to_name.json"),
    ]
    d_rev, c_rev = {}, {}
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            disp = (data.get("InvasionDisplayType") or {})
            char = (data.get("InvasionCharacterGrunt") or {})
            d_rev = {str(v): str(k) for k, v in disp.items()}
            c_rev = {str(v): str(k) for k, v in char.items()}
            break
        except Exception:
            continue
    _INV_DISPLAY_REV, _INV_CHARACTER_REV = d_rev, c_rev
    return d_rev, c_rev

def _display_label(k: str) -> str:
    return _load_invasion_maps()[0].get(str(k), str(k))

def _character_label(k: str) -> str:
    return _load_invasion_maps()[1].get(str(k), str(k))

def _grunt_label(k: str) -> str:
    # Grunt IDs share the same dictionary as character IDs
    return _character_label(k)

def _pair_label(pair_key: str) -> str:
    """Turn 'display:character' -> 'DISPLAY • CHARACTER'."""
    try:
        d, c = str(pair_key).split(":", 1)
        return f"{_display_label(d)} • {_character_label(c)}"
    except Exception:
        return str(pair_key)

def _is_multi_area(d: Any) -> bool:
    return isinstance(d, dict) and "data" not in d and any(
        isinstance(v, dict) and "data" in v for v in d.values()
    )

def _blank_image(text: str = "No data") -> bytes:
    plt.figure(figsize=(8, 2.6))
    plt.axis("off")
    plt.text(0.5, 0.5, text, ha="center", va="center", fontsize=14)
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close()
    buf.seek(0)
    return buf.getvalue()

# ---------- normalizers ----------

def _norm_sum(block: dict[str, Any]) -> dict[str, Any]:
    """
    Expect: {"mode":"sum","data":{"total": N, "confirmed": {"0": n0, "1": n1}}}
    """
    data = block.get("data") or {}
    out: dict[str, Any] = {}
    t = data.get("total")
    if isinstance(t, (int, float)):
        out["total"] = float(t)
    conf = data.get("confirmed") or {}
    if isinstance(conf, dict):
        out["confirmed"] = {str(k): float(v) for k, v in conf.items() if isinstance(v, (int, float))}
    return out

def _norm_grouped(block: dict[str, Any]) -> dict[str, dict[str, float]]:
    """
    Expect (examples):
      "display_type+character": {"1:10": 35, ...}
      "grunt": {"31": 24, ...}
      "confirmed": {"0": 238}
      "total": 238
    Returns: metric -> { key -> float }
    Adds '__total__': {"total": ...} if present.
    """
    data = block.get("data") or {}
    out: dict[str, dict[str, float]] = {}
    for metric, inner in data.items():
        if metric == "total":
            continue
        if isinstance(inner, dict):
            out[str(metric)] = {str(k): float(v) for k, v in inner.items() if isinstance(v, (int, float))}
    if isinstance(data.get("total"), (int, float)):
        out["__total__"] = {"total": float(data["total"])}
    return out

def _norm_surged(block: dict[str, Any]) -> dict[str, Any]:
    """
    Expect hours:
      {"mode":"surged","data":{"hour 15": {"display_type+character": {...}, "grunt": {...}, "confirmed": {...}, "total": n}}}
    Returns hour -> per-metric dicts, with '__scalars__.total' filled when present.
    """
    data = block.get("data") or {}
    out: dict[str, Any] = {}
    for hour_key, payload in data.items():
        if not isinstance(payload, dict):
            continue
        per_metric: dict[str, dict[str, float]] = {}
        for metric, inner in payload.items():
            if isinstance(inner, dict):
                per_metric[str(metric)] = {str(k): float(v) for k, v in inner.items() if isinstance(v, (int, float))}
            elif isinstance(inner, (int, float)) and metric == "total":
                per_metric.setdefault("__scalars__", {})["total"] = float(inner)
        out[str(hour_key)] = per_metric
    return out

# ---------- public entry ----------

async def send_invasion_counterseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    interval: str,
    mode: str,                      # 'sum' | 'grouped' | 'surged' (hourly only)
    title_prefix: str = "Invasions • Counters",
) -> None:
    """
    Visuals for invasion counter series (counter_type is always 'totals').
    """
    title = f"{title_prefix} • totals • {interval} • {_format_title_suffix(area)}"

    # ---------- SUM ----------
    if mode == "sum":
        total = 0.0
        confirmed: dict[str, float] = {}

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "sum":
                    continue
                ns = _norm_sum(block)
                total += float(ns.get("total", 0.0) or 0.0)
                for k, v in (ns.get("confirmed") or {}).items():
                    confirmed[k] = confirmed.get(k, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "sum":
            ns = _norm_sum(payload)
            total = float(ns.get("total", 0.0) or 0.0)
            confirmed = ns.get("confirmed", {}) or {}
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        await inter.followup.send(f"**Total invasions:** **{_fmt_compact(total)}**", ephemeral=True)

        # Small categorical bar for confirmed (if present)
        if confirmed:
            keys = sorted(confirmed.keys(), key=lambda s: (s not in ("0","1"), s))
            labels = ["No" if k == "0" else "Yes" if k == "1" else k for k in keys]
            values = [confirmed[k] for k in keys]

            plt.figure(figsize=(7.6, 3.8))
            ax = plt.gca()
            bars = plt.bar(labels, values)
            _annotate_bars(ax, bars, values)
            plt.ylabel("Count")
            plt.title(f"{title} • sum • confirmed")
            img = _save_current_fig_to_bytes()
            return await _send_image(inter, img, f"{title} • sum", filename_slug="invasions_sum")

        return await _send_image(inter, _blank_image("No breakdowns"), title)

    # ---------- GROUPED ----------
    elif mode == "grouped":
        merged: dict[str, dict[str, float]] = {}
        total_val = 0.0

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "grouped":
                    continue
                ng = _norm_grouped(block)
                total_val += float(ng.get("__total__", {}).get("total", 0.0))
                for metric, mp in ng.items():
                    if metric == "__total__":
                        continue
                    acc = merged.setdefault(metric, {})
                    for k, v in mp.items():
                        acc[k] = acc.get(k, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "grouped":
            ng = _norm_grouped(payload)
            total_val = float(ng.get("__total__", {}).get("total", 0.0))
            merged = {k: v for k, v in ng.items() if k != "__total__"}
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        await inter.followup.send(f"**Total invasions:** **{_fmt_compact(total_val)}**", ephemeral=True)
        if not merged:
            return await _send_image(inter, _blank_image("No data"), title)

        # 1) display_type+character → Top-15 (horizontal)
        dpc = merged.get("display_type+character", {})
        if dpc:
            top = sorted(dpc.items(), key=lambda kv: kv[1], reverse=True)[:15]
            labels = [_pair_label(k) for k, _ in top]
            values = [v for _, v in top]

            plt.figure(figsize=(11.0, 6.6))
            ax = plt.gca()
            y = list(range(len(labels)))
            bars = plt.barh(y, values)
            plt.yticks(y, labels)
            plt.gca().invert_yaxis()
            _annotate_bars_h(ax, bars, values)
            plt.xlabel("Count")
            plt.title(f"{title} • grouped • display_type+character (top {len(labels)})")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • display_type+character",
                filename_slug="invasions_grouped_display_character"
            )

        # 2) grunt → Top-15 (horizontal)
        gr = merged.get("grunt", {})
        if gr:
            top = sorted(gr.items(), key=lambda kv: kv[1], reverse=True)[:15]
            labels = [_grunt_label(k) for k, _ in top]
            values = [v for _, v in top]

            plt.figure(figsize=(10.6, 6.0))
            ax = plt.gca()
            y = list(range(len(labels)))
            bars = plt.barh(y, values)
            plt.yticks(y, labels)
            plt.gca().invert_yaxis()
            _annotate_bars_h(ax, bars, values)
            plt.xlabel("Count")
            plt.title(f"{title} • grouped • grunt (top {len(labels)})")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • grunt",
                filename_slug="invasions_grouped_grunt"
            )

        # 3) confirmed → Yes/No
        conf = merged.get("confirmed", {})
        if conf:
            keys = sorted(conf.keys(), key=lambda s: (s not in ("0","1"), s))
            labels = ["No" if k == "0" else "Yes" if k == "1" else k for k in keys]
            values = [conf[k] for k in keys]

            plt.figure(figsize=(7.6, 3.8))
            ax = plt.gca()
            bars = plt.bar(labels, values)
            _annotate_bars(ax, bars, values)
            plt.ylabel("Count")
            plt.title(f"{title} • grouped • confirmed")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • confirmed",
                filename_slug="invasions_grouped_confirmed"
            )

        return

    # ---------- SURGED (hourly only) ----------
    elif mode == "surged":
        hours_map: dict[str, dict[str, dict[str, float]]] = {}  # hour -> metric -> {k -> v}
        totals_by_hour: dict[str, float] = {}

        def _merge_hour_block(hblock: dict[str, Any]) -> None:
            for hour_key, metrics in hblock.items():
                acc_metrics = hours_map.setdefault(hour_key, {})
                t = (metrics.get("__scalars__", {}) or {}).get("total", 0.0)
                totals_by_hour[hour_key] = totals_by_hour.get(hour_key, 0.0) + float(t)
                for metric, inner in metrics.items():
                    if metric == "__scalars__":
                        continue
                    acc = acc_metrics.setdefault(metric, {})
                    for k, v in inner.items():
                        acc[k] = acc.get(k, 0.0) + v

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "surged":
                    continue
                ns = _norm_surged(block)
                _merge_hour_block(ns)
        elif isinstance(payload, dict) and payload.get("mode") == "surged":
            ns = _norm_surged(payload)
            _merge_hour_block(ns)
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        if not hours_map:
            return await _send_image(inter, _blank_image("No data"), title)

        total_all = sum(totals_by_hour.values())
        await inter.followup.send(f"**Total invasions (surged):** **{_fmt_compact(total_all)}**", ephemeral=True)

        def _hour_num(h: str) -> int:
            s = str(h).lower().strip()
            if s.startswith("hour "):
                s = s.split(" ", 1)[1]
            try:
                return int(s)
            except Exception:
                return 0

        x_hours = sorted(hours_map.keys(), key=_hour_num)
        if x_hours:
            lines = ["**Invasions by hour:**"]
            for hk in x_hours:
                lines.append(f"• Hour {_hour_num(hk)} — {_fmt_compact(totals_by_hour.get(hk, 0))}")
            await inter.followup.send("\n".join(lines), ephemeral=True)

        idx = list(range(len(x_hours)))

        # 1) Top-N display_type+character by hour (grouped bars)
        dpc_total: dict[str, float] = {}
        for h in x_hours:
            for k, v in (hours_map.get(h, {}).get("display_type+character", {}) or {}).items():
                dpc_total[k] = dpc_total.get(k, 0.0) + v

        if dpc_total:
            top_keys = [k for k, _ in sorted(dpc_total.items(), key=lambda kv: kv[1], reverse=True)[:8]]
            n_series = max(1, len(top_keys))
            width = 0.8 / n_series

            plt.figure(figsize=(11.6, 5.6))
            ax = plt.gca()
            for i, key in enumerate(top_keys):
                y_vals = [float(hours_map.get(h, {}).get("display_type+character", {}).get(key, 0.0)) for h in x_hours]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offsets, y_vals, width=width, label=_pair_label(key))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(_hour_num(h)) for h in x_hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged • top display+character")
            plt.legend(fontsize=8, ncols=2, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • surged • display_character",
                filename_slug="invasions_surged_display_character"
            )

        # 2) Top-N grunt by hour (grouped bars) — optional second chart
        gr_total: dict[str, float] = {}
        for h in x_hours:
            for k, v in (hours_map.get(h, {}).get("grunt", {}) or {}).items():
                gr_total[k] = gr_total.get(k, 0.0) + v

        if gr_total:
            top_g = [k for k, _ in sorted(gr_total.items(), key=lambda kv: kv[1], reverse=True)[:8]]
            n_series = max(1, len(top_g))
            width = 0.8 / n_series

            plt.figure(figsize=(11.2, 5.4))
            ax = plt.gca()
            for i, key in enumerate(top_g):
                y_vals = [float(hours_map.get(h, {}).get("grunt", {}).get(key, 0.0)) for h in x_hours]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offsets, y_vals, width=width, label=_grunt_label(key))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(_hour_num(h)) for h in x_hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged • top grunts")
            plt.legend(fontsize=8, ncols=2, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • surged • grunt",
                filename_slug="invasions_surged_grunt"
            )

        # 3) confirmed by hour (Yes/No) — compact if present
        conf_levels = sorted({k for h in x_hours for k in (hours_map.get(h, {}).get("confirmed", {}) or {}).keys()},
                             key=lambda s: (s not in ("0","1"), s))
        if conf_levels:
            n_series = max(1, len(conf_levels))
            width = 0.8 / n_series

            plt.figure(figsize=(9.8, 4.4))
            ax = plt.gca()
            for i, k in enumerate(conf_levels):
                y_vals = [float(hours_map.get(h, {}).get("confirmed", {}).get(k, 0.0)) for h in x_hours]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                label = "Yes" if k == "1" else "No" if k == "0" else str(k)
                bars = plt.bar(offsets, y_vals, width=width, label=label)
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(_hour_num(h)) for h in x_hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged • confirmed")
            if len(conf_levels) <= 6:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • surged • confirmed",
                filename_slug="invasions_surged_confirmed"
            )

        return

    # ---------- fallback ----------
    return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title)

# --- Invasions • Timeseries ---------------------------------------------------

def _is_multi_area_timeseries(d: Any) -> bool:
    # timeseries(grouped/surged) comes as area -> block or just a block
    return isinstance(d, dict) and "mode" not in d and any(
        isinstance(v, dict) and v.get("mode") in ("sum", "grouped", "surged") for v in d.values()
    )

def _norm_ts_sum(block: dict[str, Any]) -> dict[str, Any]:
    # {"mode":"sum","data":{"total": N, "confirmed":{"0": n0, "1": n1}}}
    data = block.get("data") or {}
    out: dict[str, Any] = {}
    if isinstance(data.get("total"), (int, float)):
        out["total"] = float(data["total"])
    conf = data.get("confirmed") or {}
    if isinstance(conf, dict):
        out["confirmed"] = {str(k): float(v) for k, v in conf.items() if isinstance(v, (int, float))}
    return out

def _norm_ts_grouped(block: dict[str, Any]) -> dict[str, dict[int, float]]:
    """
    Expect (per block):
      {
        "mode":"grouped",
        "data": {
          "<display>:<grunt>:<confirmed>": { "<epoch>": count, ... },
          ...
        }
      }
    Return: key -> { epoch_sec -> count }
    """
    data = block.get("data") or {}
    out: dict[str, dict[int, float]] = {}
    for key, tsmap in data.items():
        if not isinstance(tsmap, dict):
            continue
        mp: dict[int, float] = {}
        for t, v in tsmap.items():
            try:
                ti = int(t)
            except Exception:
                continue
            if isinstance(v, (int, float)):
                mp[ti] = mp.get(ti, 0.0) + float(v)
        if mp:
            out[str(key)] = mp
    return out

def _norm_ts_surged(block: dict[str, Any]) -> dict[str, dict[str, float]]:
    """
    Expect:
      {
        "mode":"surged",
        "data": {
          "<display>:<grunt>:<confirmed>": { "hour 14": 3, "hour 15": 5, ... },
          ...
        }
      }
    Return: key -> { "hour 14": count, ... }
    """
    data = block.get("data") or {}
    out: dict[str, dict[str, float]] = {}
    for key, hours in data.items():
        if not isinstance(hours, dict):
            continue
        out[str(key)] = {str(h): float(v) for h, v in hours.items() if isinstance(v, (int, float))}
    return out

def _tskey_label(tskey: str) -> str:
    """
    tskey format: "<display>:<grunt>:<confirmed>"
    Render as: "DISPLAY • GRUNT • Yes/No"
    """
    parts = (str(tskey).split(":") + ["", "", ""])[:3]
    display_id, grunt_id, conf_id = parts
    conf_lbl = "Yes" if conf_id == "1" else "No" if conf_id == "0" else conf_id
    return f"{_display_label(display_id)} • {_grunt_label(grunt_id)} • {conf_lbl}"

async def send_invasion_timeseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    mode: str,                      # 'sum' | 'grouped' | 'surged' (hourly only)
    title_prefix: str = "Invasions • Timeseries",
) -> None:
    """
    Timeseries visuals for invasions.
    - sum: just totals + confirmed split
    - grouped: top-N (by overall count) categories as lines over time
    - surged: grouped bars by hour for top-N categories
    """
    title = f"{title_prefix} • {_format_title_suffix(area)}"

    # ---------------- SUM ----------------
    if mode == "sum":
        total = 0.0
        confirmed: dict[str, float] = {}

        if _is_multi_area_timeseries(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "sum":
                    continue
                ns = _norm_ts_sum(block)
                total += float(ns.get("total", 0.0) or 0.0)
                for k, v in (ns.get("confirmed") or {}).items():
                    confirmed[k] = confirmed.get(k, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "sum":
            ns = _norm_ts_sum(payload)
            total = float(ns.get("total", 0.0) or 0.0)
            confirmed = ns.get("confirmed", {}) or {}
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        await inter.followup.send(f"**Total invasions:** **{_fmt_compact(total)}**", ephemeral=True)

        if confirmed:
            keys = sorted(confirmed.keys(), key=lambda s: (s not in ("0","1"), s))
            labels = ["No" if k == "0" else "Yes" if k == "1" else k for k in keys]
            values = [confirmed[k] for k in keys]

            plt.figure(figsize=(7.6, 3.8))
            ax = plt.gca()
            bars = plt.bar(labels, values)
            _annotate_bars(ax, bars, values)
            plt.ylabel("Count")
            plt.title(f"{title} • sum • confirmed")
            img = _save_current_fig_to_bytes()
            return await _send_image(inter, img, f"{title} • sum", filename_slug="invasions_ts_sum")

        return await _send_image(inter, _blank_image("No breakdowns"), title)

    # ---------------- GROUPED ----------------
    elif mode == "grouped":
        merged: dict[str, dict[int, float]] = {}

        def _merge_grouped(block: dict[str, Any]) -> None:
            ng = _norm_ts_grouped(block)
            for k, tsmap in ng.items():
                acc = merged.setdefault(k, {})
                for t, v in tsmap.items():
                    acc[t] = acc.get(t, 0.0) + v

        if _is_multi_area_timeseries(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "grouped":
                    continue
                _merge_grouped(block)
        elif isinstance(payload, dict) and payload.get("mode") == "grouped":
            _merge_grouped(payload)
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        if not merged:
            return await _send_image(inter, _blank_image("No data"), title)

        # Pick top-N series by total count
        totals = {k: sum(tsmap.values()) for k, tsmap in merged.items()}
        top_keys = [k for k, _ in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]]

        # Build unified time axis (sorted)
        all_ts = sorted({t for mp in merged.values() for t in mp.keys()})
        if not all_ts:
            return await _send_image(inter, _blank_image("No timestamps"), title)

        # Convert to datetime for nicer x-axis
        x_dt = [datetime.utcfromtimestamp(t) for t in all_ts]

        plt.figure(figsize=(12.0, 5.6))
        ax = plt.gca()
        for k in top_keys:
            series = merged.get(k, {})
            y = [series.get(t, 0.0) for t in all_ts]
            plt.plot(x_dt, y, marker="o", linewidth=1.8, markersize=3.5, label=_tskey_label(k))

        plt.xlabel("Time (UTC)")
        plt.ylabel("Count")
        plt.title(f"{title} • grouped (top {len(top_keys)})")
        if len(top_keys) <= 10:
            plt.legend(fontsize=8, ncols=2, loc="upper left")
        plt.xticks(rotation=25, ha="right")
        plt.tight_layout()
        img = _save_current_fig_to_bytes()
        return await _send_image(
            inter, img,
            f"{title} • grouped",
            filename_slug="invasions_ts_grouped"
        )

    # ---------------- SURGED (hourly only) ----------------
    elif mode == "surged":
        merged: dict[str, dict[str, float]] = {}

        def _merge_surged(block: dict[str, Any]) -> None:
            ns = _norm_ts_surged(block)
            for k, hourmap in ns.items():
                acc = merged.setdefault(k, {})
                for h, v in hourmap.items():
                    acc[h] = acc.get(h, 0.0) + v

        if _is_multi_area_timeseries(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "surged":
                    continue
                _merge_surged(block)
        elif isinstance(payload, dict) and payload.get("mode") == "surged":
            _merge_surged(payload)
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        if not merged:
            return await _send_image(inter, _blank_image("No data"), title)

        # Totals by hour (for the chat summary)
        def _hour_num(h: str) -> int:
            s = str(h).lower().strip()
            if s.startswith("hour "):
                s = s.split(" ", 1)[1]
            try:
                return int(s)
            except Exception:
                return 0

        hours = sorted({h for mp in merged.values() for h in mp.keys()}, key=_hour_num)
        totals_by_hour: dict[str, float] = {h: 0.0 for h in hours}
        for mp in merged.values():
            for h, v in mp.items():
                totals_by_hour[h] = totals_by_hour.get(h, 0.0) + float(v)

        total_all = sum(totals_by_hour.values())
        await inter.followup.send(f"**Total invasions (surged):** **{_fmt_compact(total_all)}**", ephemeral=True)
        if hours:
            lines = ["**Invasions by hour:**"]
            for h in hours:
                lines.append(f"• Hour {_hour_num(h)} — {_fmt_compact(totals_by_hour.get(h, 0))}")
            await inter.followup.send("\n".join(lines), ephemeral=True)

        # Top-N categories by overall count across hours
        totals = {k: sum(mp.values()) for k, mp in merged.items()}
        top_keys = [k for k, _ in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]]

        # Grouped bars by hour for top keys
        idx = list(range(len(hours)))
        n_series = max(1, len(top_keys))
        width = 0.8 / n_series

        plt.figure(figsize=(11.6, 5.6))
        ax = plt.gca()
        for i, k in enumerate(top_keys):
            y_vals = [float(merged.get(k, {}).get(h, 0.0)) for h in hours]
            offsets = [x - 0.4 + i * width + width / 2 for x in idx]
            bars = plt.bar(offsets, y_vals, width=width, label=_tskey_label(k))
            _annotate_bars(ax, bars, y_vals)

        plt.xticks(idx, [str(_hour_num(h)) for h in hours])
        plt.xlabel("Hour")
        plt.ylabel("Count")
        plt.title(f"{title} • surged (top {len(top_keys)})")
        plt.legend(fontsize=8, ncols=2, loc="upper left")
        img = _save_current_fig_to_bytes()
        return await _send_image(
            inter, img,
            f"{title} • surged",
            filename_slug="invasions_ts_surged"
        )

    # -------------- fallback --------------
    return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title)
