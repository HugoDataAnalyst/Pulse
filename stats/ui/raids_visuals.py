# stats/ui/raids_visuals.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import os
import json
import io

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import discord

# Pull shared helpers
from stats.psyduckv2.utils.visual_helpers import (
    _fmt_compact,
    _annotate_bars,
    _annotate_bars_h,
    _metric_color,
    _pidform_label,
    _save_current_fig_to_bytes,
    _send_image,
    _format_title_suffix,
)

# ---------- local (raid-specific) helpers ----------

_RAID_LEVEL_REV: dict[str, str] | None = None  # "1" -> "RAID_LEVEL_1", "6"->"RAID_LEVEL_MEGA", ...
def _load_raid_level_map() -> dict[str, str]:
    """
    Loads RAIDS mapping from id_to_name.json and returns a reverse map:
      {"1": "RAID_LEVEL_1", "6": "RAID_LEVEL_MEGA", ...}
    Falls back to empty dict (keys will render as-is).
    """
    global _RAID_LEVEL_REV
    if _RAID_LEVEL_REV is not None:
        return _RAID_LEVEL_REV

    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "stats", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "id_to_name.json"),
    ]
    rev: dict[str, str] = {}
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            raids = (data or {}).get("RAIDS") or {}
            # file is enum_name -> id  ==> reverse to id -> enum_name
            rev = {str(v): str(k) for k, v in raids.items()}
            break
        except Exception:
            continue

    _RAID_LEVEL_REV = rev
    return rev

def _raid_level_label(level_key: str) -> str:
    rev = _load_raid_level_map()
    return rev.get(str(level_key), str(level_key))

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
    Expect shape:
      {"mode":"sum","data":{"total": N, "raid_level": {...}}}
    Returns a dict with numeric leaves where possible.
    """
    data = block.get("data") or {}
    out: dict[str, Any] = {}
    # total
    t = data.get("total")
    if isinstance(t, (int, float)): out["total"] = float(t)
    # raid_level breakdown
    rl = data.get("raid_level") or {}
    if isinstance(rl, dict):
        out["raid_level"] = {str(k): float(v) for k, v in rl.items() if isinstance(v, (int, float))}
    return out

def _norm_grouped(block: dict[str, Any]) -> dict[str, dict[str, float]]:
    """
    Expect shape:
      {"mode":"grouped","data":{
          "raid_pokemon+raid_form": {"105:80": 13, ...},
          "raid_level": {"1": 41, ...},
          "raid_costume": {"0": 159, "77": 19},
          "raid_is_exclusive": {"0": 178},
          "raid_ex_eligible": {"0": 137, "1": 41},
          "total": 178
      }}
    Returns: metric -> { key -> float }
    (Skips 'total' in the dict; we’ll compute totals separately.)
    """
    data = block.get("data") or {}
    out: dict[str, dict[str, float]] = {}
    for metric, inner in data.items():
        if metric == "total":
            # skip; we'll read it separately when present
            continue
        if isinstance(inner, dict):
            out[str(metric)] = {str(k): float(v) for k, v in inner.items() if isinstance(v, (int, float))}
    # include 'total' as a pseudo-metric map for convenience if present (single-entry)
    if isinstance(data.get("total"), (int, float)):
        out["__total__"] = {"total": float(data.get("total"))}
    return out

def _norm_surged(block: dict[str, Any]) -> dict[str, Any]:
    """
    Expect shape:
      {"mode":"surged","data":{
         "hour 15": { "raid_level": {...}, "raid_pokemon+raid_form": {...}, "total": n15 },
         "hour 16": { ... }, ...
      }}
    Return hour -> per-metric dicts with numeric leaves only.
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

async def send_raid_counterseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    interval: str,
    mode: str,                      # 'sum' | 'grouped' | 'surged' (hourly only)
    title_prefix: str = "Raids • Counters",
) -> None:
    """
    Visuals for raid counter series (counter_type is always 'totals').
    """
    title = f"{title_prefix} • totals • {interval} • {_format_title_suffix(area)}"

    # ---------- SUM ----------
    if mode == "sum":
        total = 0.0
        raid_level: dict[str, float] = {}

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "sum":
                    continue
                ns = _norm_sum(block)
                total += float(ns.get("total", 0.0) or 0.0)
                for lvl, v in (ns.get("raid_level") or {}).items():
                    raid_level[lvl] = raid_level.get(lvl, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "sum":
            ns = _norm_sum(payload)
            total = float(ns.get("total", 0.0) or 0.0)
            raid_level = ns.get("raid_level", {}) or {}
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        await inter.followup.send(f"**Total raids:** **{_fmt_compact(total)}**", ephemeral=True)

        if not raid_level:
            return await _send_image(inter, _blank_image("No raid level data"), title)

        # Sort raid levels by numeric order if possible
        def _lvl_order(k: str) -> Tuple[int, str]:
            try:
                return (0, int(k), k)
            except Exception:
                return (1, 0, k)

        levels = sorted(raid_level.keys(), key=_lvl_order)
        labels = [_raid_level_label(k) for k in levels]
        values = [raid_level[k] for k in levels]

        plt.figure(figsize=(10.2, 4.6))
        ax = plt.gca()
        bars = plt.bar(labels, values, color=(0.4, 0.6, 0.9))
        _annotate_bars(ax, bars, values)
        plt.xticks(rotation=20, ha="right")
        plt.ylabel("Count")
        plt.title(f"{title} • sum • raid_level")
        img = _save_current_fig_to_bytes()
        return await _send_image(inter, img, f"{title} • sum", filename_slug="raids_sum")

    # ---------- GROUPED ----------
    elif mode == "grouped":
        merged: dict[str, dict[str, float]] = {}
        total_val = 0.0

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "grouped":
                    continue
                ng = _norm_grouped(block)
                # pull synthetic total if present
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

        await inter.followup.send(f"**Total raids:** **{_fmt_compact(total_val)}**", ephemeral=True)
        if not merged:
            return await _send_image(inter, _blank_image("No data"), title)

        # 1) raid_pokemon+raid_form → Top-15 horizontal bars
        rp = merged.get("raid_pokemon+raid_form", {})
        if rp:
            top = sorted(rp.items(), key=lambda kv: kv[1], reverse=True)[:15]
            labels = [_pidform_label(k) for k, _ in top]
            values = [v for _, v in top]

            plt.figure(figsize=(10.8, 6.4))
            ax = plt.gca()
            y = list(range(len(labels)))
            bars = plt.barh(y, values, color=_metric_color("shiny"))  # just a distinct color
            plt.yticks(y, labels)
            plt.gca().invert_yaxis()
            _annotate_bars_h(ax, bars, values)
            plt.xlabel("Count")
            plt.title(f"{title} • grouped • raid_pokemon (top {len(labels)})")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • raid_pokemon",
                filename_slug="raids_grouped_raid_pokemon"
            )

        # 2) raid_level → vertical bars
        rl = merged.get("raid_level", {})
        if rl:
            def _lvl_order(k: str) -> Tuple[int, str]:
                try:
                    return (0, int(k), k)
                except Exception:
                    return (1, 0, k)

            levels = sorted(rl.keys(), key=_lvl_order)
            labels = [_raid_level_label(k) for k in levels]
            values = [rl[k] for k in levels]

            plt.figure(figsize=(10.2, 4.8))
            ax = plt.gca()
            bars = plt.bar(labels, values, color=(0.4, 0.6, 0.9))
            _annotate_bars(ax, bars, values)
            plt.xticks(rotation=20, ha="right")
            plt.ylabel("Count")
            plt.title(f"{title} • grouped • raid_level")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • raid_level",
                filename_slug="raids_grouped_raid_level"
            )

        # 3) Simple categorical metrics
        for metric_name in ("raid_costume", "raid_is_exclusive", "raid_ex_eligible"):
            mp = merged.get(metric_name, {})
            if not mp:
                continue
            keys = sorted(mp.keys(), key=lambda s: (s not in ("0","1"), s))
            # Friendly-ish labels
            if metric_name in ("raid_is_exclusive", "raid_ex_eligible"):
                lbls = ["No" if k == "0" else "Yes" if k == "1" else k for k in keys]
            elif metric_name == "raid_costume":
                lbls = ["None" if k == "0" else k for k in keys]
            else:
                lbls = keys
            vals = [mp[k] for k in keys]

            plt.figure(figsize=(8.8, 4.2))
            ax = plt.gca()
            bars = plt.bar(lbls, vals, color=(0.6, 0.6, 0.6))
            _annotate_bars(ax, bars, vals)
            plt.xticks(rotation=15, ha="right")
            plt.ylabel("Count")
            plt.title(f"{title} • grouped • {metric_name}")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • {metric_name}",
                filename_slug=f"raids_grouped_{metric_name}"
            )

        return

    # ---------- SURGED (hourly only) ----------
    elif mode == "surged":
        # Merge hour buckets across areas
        hours_map: dict[str, dict[str, dict[str, float]]] = {}  # hour -> metric -> {k -> v}
        totals_by_hour: dict[str, float] = {}

        def _merge_hour_block(hblock: dict[str, Any]) -> None:
            for hour_key, metrics in hblock.items():
                acc_metrics = hours_map.setdefault(hour_key, {})
                # pull '__scalars__' / 'total'
                t = (metrics.get("__scalars__", {}) or {}).get("total", 0.0)
                totals_by_hour[hour_key] = totals_by_hour.get(hour_key, 0.0) + float(t)
                # fold metric maps
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

        # Totals (surged) summary + list by hour
        total_all = sum(totals_by_hour.values())
        await inter.followup.send(f"**Total raids (surged):** **{_fmt_compact(total_all)}**", ephemeral=True)

        def hour_num(h: str) -> int:
            s = str(h).lower().strip()
            return int(s.split(" ", 1)[1]) if s.startswith("hour ") and s.split(" ", 1)[1].isdigit() else (
                int(s) if s.isdigit() else 0
            )

        x_hours = sorted(hours_map.keys(), key=hour_num)
        if x_hours:
            lines = ["**Raids by hour:**"]
            for hk in x_hours:
                lines.append(f"• Hour {hour_num(hk)} — {_fmt_compact(totals_by_hour.get(hk, 0))}")
            await inter.followup.send("\n".join(lines), ephemeral=True)

        # Chart 1: raid_level clustered bars over hours
        rl_by_hour = [hours_map.get(h, {}).get("raid_level", {}) for h in x_hours]
        all_levels = sorted(
            {lvl for mp in rl_by_hour for lvl in mp.keys()},
            key=lambda k: (0, int(k)) if str(k).isdigit() else (1, 0)
        )
        if all_levels:
            idx = list(range(len(x_hours)))
            n_series = max(1, len(all_levels))
            width = 0.8 / n_series

            plt.figure(figsize=(11.2, 5.4))
            ax = plt.gca()
            for i, lvl in enumerate(all_levels):
                y_vals = [float(mp.get(lvl, 0.0)) for mp in rl_by_hour]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offsets, y_vals, width=width, label=_raid_level_label(lvl))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(hour_num(h)) for h in x_hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged • raid_level")
            if len(all_levels) <= 12:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • surged • raid_level",
                filename_slug="raids_surged_raid_level"
            )

        # Chart 2: raid_pokemon+raid_form (Top-N per whole window), then show their hourly trend
        rp_total: dict[str, float] = {}
        for h in x_hours:
            for k, v in (hours_map.get(h, {}).get("raid_pokemon+raid_form", {}) or {}).items():
                rp_total[k] = rp_total.get(k, 0.0) + v

        if rp_total:
            top_keys = [k for k, _ in sorted(rp_total.items(), key=lambda kv: kv[1], reverse=True)[:8]]
            idx = list(range(len(x_hours)))
            n_series = max(1, len(top_keys))
            width = 0.8 / n_series

            plt.figure(figsize=(11.6, 5.6))
            ax = plt.gca()
            for i, pf in enumerate(top_keys):
                y_vals = [float(hours_map.get(h, {}).get("raid_pokemon+raid_form", {}).get(pf, 0.0)) for h in x_hours]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offsets, y_vals, width=width, label=_pidform_label(pf))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(hour_num(h)) for h in x_hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged • top raid_pokemon")
            plt.legend(fontsize=8, ncols=2, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • surged • raid_pokemon",
                filename_slug="raids_surged_raid_pokemon"
            )

        return

    # ---------- fallback ----------
    return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title)

async def send_raid_timeseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    mode: str,
    title_prefix: str,
) -> None:
    """
    SUM:
      Aggregate across areas when global; post Total raids; chart raid_level.
    GROUPED:
      One Top-15 chart for raid_pokemon+raid_form; chart raid_level.
    SURGED:
      Aggregate by hour across areas; list totals by hour; chart raid_level by hour (grouped bars);
      chart Top-N raid_pokemon+raid_form by hour (grouped bars).
    """
    title = f"{title_prefix} • {_format_title_suffix(area)}"

    # ---------- SUM ----------
    if mode == "sum":
        total = 0.0
        raid_level: dict[str, float] = {}

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "sum":
                    continue
                ns = _norm_sum(block)
                total += float(ns.get("total", 0.0) or 0.0)
                for lvl, v in (ns.get("raid_level") or {}).items():
                    raid_level[lvl] = raid_level.get(lvl, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "sum":
            ns = _norm_sum(payload)
            total = float(ns.get("total", 0.0) or 0.0)
            raid_level = ns.get("raid_level", {}) or {}
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        await inter.followup.send(f"**Total raids:** **{_fmt_compact(total)}**", ephemeral=True)

        if not raid_level:
            return await _send_image(inter, _blank_image("No raid level data"), title)

        def _lvl_sort(k: str) -> tuple[int, int, str]:
            try: return (0, int(k), k)
            except Exception: return (1, 0, k)

        levels = sorted(raid_level.keys(), key=_lvl_sort)
        labels = [_raid_level_label(k) for k in levels]
        values = [raid_level[k] for k in levels]

        plt.figure(figsize=(10.2, 4.8))
        ax = plt.gca()
        bars = plt.bar(labels, values, color=(0.4, 0.6, 0.9))
        _annotate_bars(ax, bars, values)
        plt.xticks(rotation=20, ha="right")
        plt.ylabel("Count")
        plt.title(f"{title} • sum • raid_level")
        img = _save_current_fig_to_bytes()
        return await _send_image(inter, img, f"{title} • sum", filename_slug="raids_timeseries_sum")

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

        await inter.followup.send(f"**Total raids:** **{_fmt_compact(total_val)}**", ephemeral=True)
        if not merged:
            return await _send_image(inter, _blank_image("No data"), title)

        # A) raid_pokemon+raid_form → Top-15 horizontal
        rp = merged.get("raid_pokemon+raid_form", {})
        if rp:
            top = sorted(rp.items(), key=lambda kv: kv[1], reverse=True)[:15]
            labels = [_pidform_label(k) for k, _ in top]
            values = [v for _, v in top]

            plt.figure(figsize=(10.8, 6.4))
            ax = plt.gca()
            y = list(range(len(labels)))
            bars = plt.barh(y, values, color=_metric_color("iv100"))
            plt.yticks(y, labels)
            plt.gca().invert_yaxis()
            _annotate_bars_h(ax, bars, values)
            plt.xlabel("Count")
            plt.title(f"{title} • grouped • raid_pokemon (top {len(labels)})")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • raid_pokemon",
                filename_slug="raids_timeseries_grouped_raid_pokemon"
            )

        # B) raid_level → vertical bars
        rl = merged.get("raid_level", {})
        if rl:
            def _lvl_sort(k: str) -> tuple[int, int, str]:
                try: return (0, int(k), k)
                except Exception: return (1, 0, k)

            levels = sorted(rl.keys(), key=_lvl_sort)
            labels = [_raid_level_label(k) for k in levels]
            values = [rl[k] for k in levels]

            plt.figure(figsize=(10.2, 4.8))
            ax = plt.gca()
            bars = plt.bar(labels, values, color=(0.4, 0.6, 0.9))
            _annotate_bars(ax, bars, values)
            plt.xticks(rotation=20, ha="right")
            plt.ylabel("Count")
            plt.title(f"{title} • grouped • raid_level")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • grouped • raid_level",
                filename_slug="raids_timeseries_grouped_raid_level"
            )

        return

    # ---------- SURGED (hourly) ----------
    elif mode == "surged":
        hours_map: dict[str, dict[str, dict[str, float]]] = {}
        totals_by_hour: dict[str, float] = {}

        def _merge_hour_block(hblock: dict[str, Any]) -> None:
            for hour_key, metrics in hblock.items():
                acc_metrics = hours_map.setdefault(hour_key, {})
                t = (metrics.get("__scalars__", {}) or {}).get("total", 0.0)
                totals_by_hour[hour_key] = totals_by_hour.get(hour_key, 0.0) + float(t)
                for metric, mp in metrics.items():
                    if metric == "__scalars__":
                        continue
                    acc = acc_metrics.setdefault(metric, {})
                    for k, v in mp.items():
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
        await inter.followup.send(f"**Total raids (surged):** **{_fmt_compact(total_all)}**", ephemeral=True)

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
            lines = ["**Raids by hour:**"]
            for hk in x_hours:
                lines.append(f"• Hour {_hour_num(hk)} — {_fmt_compact(totals_by_hour.get(hk, 0))}")
            await inter.followup.send("\n".join(lines), ephemeral=True)

        # 1) raid_level clustered bars over hours
        rl_by_hour = [hours_map.get(h, {}).get("raid_level", {}) for h in x_hours]
        all_levels = sorted(
            {lvl for mp in rl_by_hour for lvl in mp.keys()},
            key=lambda k: (0, int(k)) if str(k).isdigit() else (1, 0)
        )
        if all_levels:
            idx = list(range(len(x_hours)))
            n_series = max(1, len(all_levels))
            width = 0.8 / n_series

            plt.figure(figsize=(11.2, 5.4))
            ax = plt.gca()
            for i, lvl in enumerate(all_levels):
                y_vals = [float(mp.get(lvl, 0.0)) for mp in rl_by_hour]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offsets, y_vals, width=width, label=_raid_level_label(lvl))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(_hour_num(h)) for h in x_hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged • raid_level")
            if len(all_levels) <= 12:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • surged • raid_level",
                filename_slug="raids_timeseries_surged_raid_level"
            )

        # 2) Top-N raid_pokemon+raid_form by hour (grouped bars)
        rp_total: dict[str, float] = {}
        for h in x_hours:
            for k, v in (hours_map.get(h, {}).get("raid_pokemon+raid_form", {}) or {}).items():
                rp_total[k] = rp_total.get(k, 0.0) + v

        if rp_total:
            top_keys = [k for k, _ in sorted(rp_total.items(), key=lambda kv: kv[1], reverse=True)[:8]]
            idx = list(range(len(x_hours)))
            n_series = max(1, len(top_keys))
            width = 0.8 / n_series

            plt.figure(figsize=(11.6, 5.6))
            ax = plt.gca()
            for i, pf in enumerate(top_keys):
                y_vals = [float(hours_map.get(h, {}).get("raid_pokemon+raid_form", {}).get(pf, 0.0)) for h in x_hours]
                offsets = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offsets, y_vals, width=width, label=_pidform_label(pf))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(_hour_num(h)) for h in x_hours])
            plt.xlabel("Hour")
            plt.ylabel("Count")
            plt.title(f"{title} • surged • top raid_pokemon")
            plt.legend(fontsize=8, ncols=2, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(
                inter, img,
                f"{title} • surged • raid_pokemon",
                filename_slug="raids_timeseries_surged_raid_pokemon"
            )

        return

    # ---------- fallback ----------
    return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title)
