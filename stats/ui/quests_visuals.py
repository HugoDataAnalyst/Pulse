from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import os, json, io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import discord
from datetime import datetime, timezone
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

# ---------- local helpers / mappers ----------

_QRT_REV: dict[str, str] | None = None   # QuestRewardType id->enum
_QRI_REV: dict[str, str] | None = None   # QuestRewardItem id->enum

def _load_rev_map(section: str) -> dict[str, str]:
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "stats", "psyduckv2", "utils", "id_to_name.json"),
        os.path.join(os.getcwd(), "id_to_name.json"),
    ]
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            sec = (data or {}).get(section) or {}
            return {str(v): str(k) for k, v in sec.items()}
        except Exception:
            continue
    return {}

def _reward_type_label(code: str) -> str:
    global _QRT_REV
    if _QRT_REV is None:
        _QRT_REV = _load_rev_map("QuestRewardType")
    if code == "None":
        return "None"
    return _QRT_REV.get(str(code), str(code))

def _reward_item_label(code: str) -> str:
    global _QRI_REV
    if _QRI_REV is None:
        _QRI_REV = _load_rev_map("QuestRewardItem")
    if code == "None":
        return "None"
    return _QRI_REV.get(str(code), str(code))

def _poke_label_from_id(pid_key: str) -> str:
    # reward_poke is only the Pokémon ID; use base form 0 for label
    if pid_key == "None":
        return "None"
    return _pidform_label(f"{pid_key}:0")

def _is_multi_area(d: Any) -> bool:
    return isinstance(d, dict) and "data" not in d and any(
        isinstance(v, dict) and "data" in v for v in d.values()
    )

def _blank_image(text: str = "No data") -> bytes:
    plt.figure(figsize=(8, 2.6)); plt.axis("off")
    plt.text(0.5, 0.5, text, ha="center", va="center", fontsize=14)
    buf = io.BytesIO()
    plt.tight_layout(); plt.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(); buf.seek(0)
    return buf.getvalue()

def _epochs_to_datetimes(xs: list[int]) -> list[datetime]:
    out: list[datetime] = []
    for e in xs:
        try:
            out.append(datetime.fromtimestamp(int(e), tz=timezone.utc))
        except Exception:
            # skip bad points defensively
            continue
    return out


# ---------- normalizers ----------

def _norm_q_sum(block: dict[str, Any]) -> dict[str, Any]:
    """
    {"mode":"sum","data":{"total": N, "quest_mode":{"ar": n_ar} }}
    """
    data = block.get("data") or {}
    out: dict[str, Any] = {}
    if isinstance(data.get("total"), (int, float)):
        out["total"] = float(data["total"])
    qm = data.get("quest_mode") or {}
    if isinstance(qm, dict):
        out["quest_mode"] = {str(k): float(v) for k, v in qm.items() if isinstance(v, (int, float))}
    return out

def _norm_q_grouped(block: dict[str, Any]) -> dict[str, dict[str, float]]:
    """
    Grouped for quests arrives time-sliced:
      {"mode":"grouped","data": { "<bucket>": { <metric>: {key: val...}, ... }, ... } }
    We collapse across buckets → metric -> { key -> total }.
    """
    data = block.get("data") or {}
    acc: dict[str, dict[str, float]] = {}
    for bucket_payload in data.values():
        if not isinstance(bucket_payload, dict):
            continue
        for metric, inner in bucket_payload.items():
            if metric == "total":  # ignore bucket-local "total"; we'll re-sum if needed
                continue
            if not isinstance(inner, dict):
                continue
            dst = acc.setdefault(str(metric), {})
            for k, v in inner.items():
                if isinstance(v, (int, float)):
                    kstr = "None" if k is None else str(k)
                    dst[kstr] = dst.get(kstr, 0.0) + float(v)
    # attach synthetic total if present
    tot = 0.0
    for b in data.values():
        if isinstance(b, dict) and isinstance(b.get("total"), (int, float)):
            tot += float(b["total"])
    if tot:
        acc["__total__"] = {"total": tot}
    return acc

def _norm_q_surged(block: dict[str, Any]) -> dict[str, dict[str, dict[str, float]]]:
    """
    Surged for quests:
      {"mode":"surged","data": { "<hour>": { <metric>: {key: val...}, "total": n }, ... } }
    Return: hour -> metric -> {key -> float} (and "__scalars__": {"total": n})
    """
    data = block.get("data") or {}
    out: dict[str, dict[str, dict[str, float]]] = {}
    for hour_key, payload in data.items():
        if not isinstance(payload, dict):
            continue
        per_metric: dict[str, dict[str, float]] = {}
        for metric, inner in payload.items():
            if metric == "total" and isinstance(inner, (int, float)):
                per_metric.setdefault("__scalars__", {})["total"] = float(inner)
                continue
            if isinstance(inner, dict):
                per_metric[str(metric)] = {str(k): float(v) for k, v in inner.items() if isinstance(v, (int, float))}
        out[str(hour_key)] = per_metric
    return out

def _plot_grouped_top_hbars(
    *,
    metric_name: str,
    data_map: dict[str, float] | None,
    base_title: str,
    top_n: int = 15,
    label_fn=lambda s: s,
    color: tuple[float, float, float] | None = None,
) -> Optional[tuple[bytes, str, str]]:
    """
    Common renderer for grouped counters as top-N horizontal bars.
    Returns (img_bytes, pretty_title, filename_slug) or None if no data.
    """
    if not data_map:
        return None

    # Top-N by value
    top = sorted(data_map.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    if not top:
        return None

    labels = [label_fn(k) for k, _ in top]
    values = [v for _, v in top]

    plt.figure(figsize=(10.8, 6.2))
    ax = plt.gca()
    y = list(range(len(labels)))
    bars = plt.barh(y, values, color=color or _metric_color("items"))
    plt.yticks(y, labels)
    plt.gca().invert_yaxis()
    _annotate_bars_h(ax, bars, values)
    plt.xlabel("Count")
    pretty_title = f"{base_title} • grouped • {metric_name} (top {len(labels)})"
    plt.title(pretty_title)
    img = _save_current_fig_to_bytes()
    slug = f"quests_grouped_{metric_name}"
    return img, pretty_title, slug


# ---------- public entry ----------

async def send_quest_counterseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    interval: str,
    mode: str,   # 'sum' | 'grouped' | 'surged'
    title_prefix: str = "Quests • Counters",
) -> None:
    """
    Visuals for quest counter-series (counter_type is always 'totals').
    """
    title = f"{title_prefix} • totals • {interval} • {_format_title_suffix(area)}"

    # ---------- SUM ----------
    if mode == "sum":
        total = 0.0
        quest_mode: dict[str, float] = {}

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "sum":
                    continue
                ns = _norm_q_sum(block)
                total += float(ns.get("total", 0.0) or 0.0)
                for k, v in (ns.get("quest_mode") or {}).items():
                    quest_mode[k] = quest_mode.get(k, 0.0) + v
        elif isinstance(payload, dict) and payload.get("mode") == "sum":
            ns = _norm_q_sum(payload)
            total = float(ns.get("total", 0.0) or 0.0)
            quest_mode = ns.get("quest_mode", {}) or {}
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        await inter.followup.send(f"**Total quests:** **{_fmt_compact(total)}**", ephemeral=True)

        if quest_mode:
            keys = sorted(quest_mode.keys(), key=lambda s: (s != "ar", s))
            labels = ["AR" if k == "ar" else k for k in keys]
            values = [quest_mode[k] for k in keys]

            plt.figure(figsize=(7.6, 3.8))
            ax = plt.gca()
            bars = plt.bar(labels, values, color=(0.4, 0.6, 0.9))
            _annotate_bars(ax, bars, values)
            plt.ylabel("Count")
            plt.title(f"{title} • sum • quest_mode")
            img = _save_current_fig_to_bytes()
            return await _send_image(inter, img, f"{title} • sum", filename_slug="quests_sum")

        return await _send_image(inter, _blank_image("No quest_mode data"), title)

    # ---------- GROUPED ----------
    elif mode == "grouped":
        merged: dict[str, dict[str, float]] = {}
        total_val = 0.0

        def _merge_grouped(block: dict[str, Any]) -> None:
            nonlocal total_val
            ng = _norm_q_grouped(block)
            total_val += float(ng.get("__total__", {}).get("total", 0.0))
            for metric, mp in ng.items():
                if metric == "__total__": continue
                acc = merged.setdefault(metric, {})
                for k, v in mp.items():
                    acc[k] = acc.get(k, 0.0) + v

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "grouped":
                    continue
                _merge_grouped(block)
        elif isinstance(payload, dict) and payload.get("mode") == "grouped":
            _merge_grouped(payload)
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        await inter.followup.send(f"**Total quests:** **{_fmt_compact(total_val)}**", ephemeral=True)
        if not merged:
            return await _send_image(inter, _blank_image("No data"), title)

        # reward_type
        rt_img = _plot_grouped_top_hbars(
            metric_name="reward_type",
            data_map=merged.get("reward_type", {}),
            base_title=title,
            top_n=15,
            label_fn=_reward_type_label,
            color=_metric_color("items"),
        )
        if rt_img:
            img, t, slug = rt_img
            await _send_image(inter, img, t, filename_slug=slug)

        # 2) reward_items
        ri_img = _plot_grouped_top_hbars(
            metric_name="reward_item",
            data_map=merged.get("reward_item", {}),
            base_title=title,
            top_n=15,
            label_fn=_reward_item_label,
            color=_metric_color("items"),
        )
        if ri_img:
            img, t, slug = ri_img
            await _send_image(inter, img, t, filename_slug=slug)

        # 3) reward_item_amount
        ria_img = _plot_grouped_top_hbars(
            metric_name="reward_item_amount",
            data_map=merged.get("reward_item_amount", {}),
            base_title=title,
            top_n=15,
            label_fn=lambda s: s,
            color=(0.6, 0.6, 0.6),
        )
        if ria_img:
            img, t, slug = ria_img
            await _send_image(inter, img, t, filename_slug=slug)

        # 4) reward_poke
        rp_img = _plot_grouped_top_hbars(
            metric_name="reward_poke",
            data_map=merged.get("reward_poke", {}),
            base_title=title,
            top_n=15,
            label_fn=_poke_label_from_id,
            color=_metric_color("shiny"),
        )
        if rp_img:
            img, t, slug = rp_img
            await _send_image(inter, img, t, filename_slug=slug)

        # 5) reward_poke_form
        rpf_img = _plot_grouped_top_hbars(
            metric_name="reward_poke_form",
            data_map=merged.get("reward_poke_form", {}),
            base_title=title,
            top_n=15,
            label_fn=lambda s: s,
            color=(0.7, 0.7, 0.7),
        )
        if rpf_img:
            img, t, slug = rpf_img
            await _send_image(inter, img, t, filename_slug=slug)

        # 6) quest_mode
        qm = merged.get("quest_mode", {})
        if qm:
            keys = sorted(qm.keys(), key=lambda s: (s != "ar", s))
            labels = ["AR" if k == "ar" else k for k in keys]
            values = [qm[k] for k in keys]

            plt.figure(figsize=(7.2, 3.2))
            ax = plt.gca()
            bars = plt.bar(labels, values, color=(0.4, 0.6, 0.9))
            _annotate_bars(ax, bars, values)
            plt.ylabel("Count")
            plt.title(f"{title} • grouped • quest_mode")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title} • grouped • quest_mode", filename_slug="quests_grouped_mode")

        return

    # ---------- SURGED (hourly only) ----------
    elif mode == "surged":
        # Merge hour buckets across areas
        hours_map: dict[str, dict[str, dict[str, float]]] = {}  # hour -> metric -> {k -> v}
        totals_by_hour: dict[str, float] = {}

        def _merge_surged_block(ns: dict[str, dict[str, dict[str, float]]]) -> None:
            for hour_key, metrics in ns.items():
                acc_metrics = hours_map.setdefault(hour_key, {})
                t = (metrics.get("__scalars__", {}) or {}).get("total", 0.0)
                totals_by_hour[hour_key] = totals_by_hour.get(hour_key, 0.0) + float(t)
                for metric, inner in metrics.items():
                    if metric == "__scalars__": continue
                    acc = acc_metrics.setdefault(metric, {})
                    for k, v in inner.items():
                        acc[k] = acc.get(k, 0.0) + v

        if _is_multi_area(payload):
            for block in payload.values():
                if not isinstance(block, dict) or block.get("mode") != "surged":
                    continue
                _merge_surged_block(_norm_q_surged(block))
        elif isinstance(payload, dict) and payload.get("mode") == "surged":
            _merge_surged_block(_norm_q_surged(payload))
        else:
            return await _send_image(inter, _blank_image("Unsupported payload"), title)

        if not hours_map:
            return await _send_image(inter, _blank_image("No data"), title)

        def hour_num(h: str) -> int:
            s = str(h).lstrip("0") or "0"
            try: return int(s)
            except Exception: return 0

        x_hours = sorted(hours_map.keys(), key=hour_num)

        # Summary by hour
        total_all = sum(totals_by_hour.values())
        await inter.followup.send(f"**Total quests (surged):** **{_fmt_compact(total_all)}**", ephemeral=True)
        if x_hours:
            lines = ["**Quests by bucket:**"]
            for hk in x_hours:
                lines.append(f"• {str(hk)} — {_fmt_compact(totals_by_hour.get(hk, 0))}")
            await inter.followup.send("\n".join(lines), ephemeral=True)

        # Chart 1: reward_type over buckets (clustered bars)
        rt_by_hour = [hours_map.get(h, {}).get("reward_type", {}) for h in x_hours]
        all_rtypes = sorted({k for mp in rt_by_hour for k in mp.keys()}, key=lambda k: (k == "None", k))
        if all_rtypes:
            idx = list(range(len(x_hours)))
            n_series = max(1, len(all_rtypes))
            width = 0.8 / n_series

            plt.figure(figsize=(11.2, 5.2))
            ax = plt.gca()
            for i, rcode in enumerate(all_rtypes):
                y_vals = [float(mp.get(rcode, 0.0)) for mp in rt_by_hour]
                offs = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offs, y_vals, width=width, label=_reward_type_label(rcode))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(h) for h in x_hours])
            plt.xlabel("Hour bucket"); plt.ylabel("Count")
            plt.title(f"{title} • surged • reward_type")
            if len(all_rtypes) <= 12:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title} • surged • reward_type", filename_slug="quests_surged_reward_type")

        # Chart 2: Top-N reward_poke across buckets (clustered bars)
        rp_total: dict[str, float] = {}
        for h in x_hours:
            for k, v in (hours_map.get(h, {}).get("reward_poke", {}) or {}).items():
                rp_total[k] = rp_total.get(k, 0.0) + v

        if rp_total:
            top_keys = [k for k, _ in sorted(rp_total.items(), key=lambda kv: kv[1], reverse=True)[:8]]
            idx = list(range(len(x_hours)))
            n_series = max(1, len(top_keys))
            width = 0.8 / n_series

            plt.figure(figsize=(11.6, 5.4))
            ax = plt.gca()
            for i, pk in enumerate(top_keys):
                y_vals = [float(hours_map.get(h, {}).get("reward_poke", {}).get(pk, 0.0)) for h in x_hours]
                offs = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offs, y_vals, width=width, label=_poke_label_from_id(pk))
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(h) for h in x_hours])
            plt.xlabel("Hour bucket"); plt.ylabel("Count")
            plt.title(f"{title} • surged • top reward_poke")
            plt.legend(fontsize=8, ncols=2, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title} • surged • reward_poke", filename_slug="quests_surged_reward_poke")

        # Chart 3 (optional): quest_mode across buckets
        qm_by_hour = [hours_map.get(h, {}).get("quest_mode", {}) for h in x_hours]
        all_modes = sorted({k for mp in qm_by_hour for k in mp.keys()}, key=lambda s: (s != "ar", s))
        if all_modes:
            idx = list(range(len(x_hours)))
            n_series = max(1, len(all_modes))
            width = 0.8 / n_series

            plt.figure(figsize=(10.8, 4.8))
            ax = plt.gca()
            for i, m in enumerate(all_modes):
                y_vals = [float(mp.get(m, 0.0)) for mp in qm_by_hour]
                offs = [x - 0.4 + i * width + width / 2 for x in idx]
                label = "AR" if m == "ar" else m
                bars = plt.bar(offs, y_vals, width=width, label=label)
                _annotate_bars(ax, bars, y_vals)

            plt.xticks(idx, [str(h) for h in x_hours])
            plt.xlabel("Hour bucket"); plt.ylabel("Count")
            plt.title(f"{title} • surged • quest_mode")
            if len(all_modes) <= 6:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title} • surged • quest_mode", filename_slug="quests_surged_quest_mode")

        return

    # ---------- fallback ----------
    return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title)

# ---------- QUESTS • TIME-SERIES  ----------

# extra reverse map for QuestTaskType (id -> enum name)
_QTT_REV: dict[str, str] | None = None  # QuestTaskType id->enum

def _quest_type_label(code: str) -> str:
    global _QTT_REV
    if _QTT_REV is None:
        _QTT_REV = _load_rev_map("QuestTaskType")
    if code == "None":
        return "None"
    return _QTT_REV.get(str(code), str(code))

def _parse_ts_key(key: str) -> Optional[dict]:
    """
    ts:quests_total:{mode}:{area}:{qtype}:{rtype}:{item_id}:{item_amt}:{poke_id}:{poke_form}
    Return dict or None if not parseable.
    """
    try:
        parts = key.split(":")
        # minimal defensive checks
        if len(parts) < 10:
            return None
        # ts | quests_total | mode | area | qtype | rtype | item | amt | poke | form
        return {
            "quest_mode": parts[2],     # 'ar' or 'normal'
            "area": parts[3],
            "quest_type": parts[4],
            "reward_type": parts[5],
            "reward_item_id": parts[6],
            "reward_item_amount": parts[7],
            "reward_poke_id": parts[8],
            "reward_poke_form": parts[9],
        }
    except Exception:
        return None

def _is_quests_ts_grouped_payload(block: dict) -> bool:
    # grouped time-series returns "data" as { ts:key -> { epoch -> count } }
    data = block.get("data")
    if not isinstance(data, dict):
        return False
    # check one entry
    for k, v in data.items():
        if isinstance(k, str) and k.startswith("ts:quests_total:") and isinstance(v, dict):
            return True
    return False

def _iter_area_blocks(payload: Any) -> list[dict]:
    """Yield per-area blocks (even if single block)."""
    if _is_multi_area(payload):
        return [b for b in payload.values() if isinstance(b, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []

def _merge_count_series(dst: dict[int, float], add: dict[int, float]) -> None:
    for t, c in add.items():
        try:
            ti = int(t)
        except Exception:
            continue
        if not isinstance(c, (int, float)): continue
        dst[ti] = dst.get(ti, 0.0) + float(c)

def _collapse_ts_grouped(blocks: list[dict]) -> dict[str, Any]:
    """
    Collapse grouped time-series across areas into:
      totals_by_ts: {epoch -> count}
      by_qtype: { qtype -> {epoch -> count} }
      by_rtype: { rtype -> {epoch -> count} }
      by_item:  { item_id -> {epoch -> count} }
      by_poke:  { poke_id -> {epoch -> count} }
    """
    totals_by_ts: dict[int, float] = {}
    by_qtype: dict[str, dict[int, float]] = {}
    by_rtype: dict[str, dict[int, float]] = {}
    by_item:  dict[str, dict[int, float]] = {}
    by_poke:  dict[str, dict[int, float]] = {}

    for b in blocks:
        if b.get("mode") != "grouped":  # ignore non-matching (defensive)
            continue
        data = b.get("data") or {}
        for ts_key, series in data.items():
            if not (isinstance(ts_key, str) and isinstance(series, dict)):
                continue
            meta = _parse_ts_key(ts_key)
            if not meta:
                continue

            # series: { epoch -> count }
            # 1) total
            _merge_count_series(totals_by_ts, {int(t): v for t, v in series.items() if isinstance(v, (int, float))})

            # 2) breakdowns
            qt = str(meta["quest_type"])
            rt = str(meta["reward_type"])
            it = str(meta["reward_item_id"])
            pk = str(meta["reward_poke_id"])

            _merge_count_series(by_qtype.setdefault(qt, {}), {int(t): v for t, v in series.items() if isinstance(v, (int, float))})
            _merge_count_series(by_rtype.setdefault(rt, {}), {int(t): v for t, v in series.items() if isinstance(v, (int, float))})
            _merge_count_series(by_item.setdefault(it, {}),   {int(t): v for t, v in series.items() if isinstance(v, (int, float))})
            _merge_count_series(by_poke.setdefault(pk, {}),   {int(t): v for t, v in series.items() if isinstance(v, (int, float))})

    return {
        "totals_by_ts": totals_by_ts,
        "by_qtype": by_qtype,
        "by_rtype": by_rtype,
        "by_item": by_item,
        "by_poke": by_poke,
    }

def _collapse_ts_surged(blocks: list[dict]) -> dict[str, Any]:
    """
    Surged time-series arrives as:
      data = { "ts:quests_total:...": {"hour 0": n, "hour 1": m, ...}, ... }
    We collapse to:
      totals_by_hour: {hour_str -> count}
      by_qtype_hour:  {qtype -> {hour_str -> count}}
      by_poke_hour:   {pid   -> {hour_str -> count}}
    """
    totals_by_hour: dict[str, float] = {}
    by_qtype_hour: dict[str, dict[str, float]] = {}
    by_poke_hour: dict[str, dict[str, float]] = {}

    for b in blocks:
        if b.get("mode") != "surged":
            continue
        data = b.get("data") or {}
        for ts_key, per_hour in data.items():
            if not (isinstance(ts_key, str) and isinstance(per_hour, dict)):
                continue
            meta = _parse_ts_key(ts_key)
            if not meta:
                continue
            qt = str(meta["quest_type"])
            pk = str(meta["reward_poke_id"])

            for hr, cnt in per_hour.items():
                if not isinstance(cnt, (int, float)): continue
                h = str(hr)
                totals_by_hour[h] = totals_by_hour.get(h, 0.0) + float(cnt)
                by_qtype_hour.setdefault(qt, {})[h] = by_qtype_hour.setdefault(qt, {}).get(h, 0.0) + float(cnt)
                by_poke_hour.setdefault(pk, {})[h]  = by_poke_hour.setdefault(pk, {}).get(h, 0.0) + float(cnt)

    return {
        "totals_by_hour": totals_by_hour,
        "by_qtype_hour": by_qtype_hour,
        "by_poke_hour": by_poke_hour,
    }

def _sorted_epoch_list(series_map: dict[int, float]) -> list[int]:
    return sorted(series_map.keys())

def _plot_simple_timeseries(x_epochs: list[int], y_vals: list[float], title: str, ylabel: str = "Count"):
    if not x_epochs:
        return _blank_image("No time-series data")
    # Convert epochs → timezone-aware datetimes (UTC)
    x_dt = _epochs_to_datetimes(x_epochs)
    plt.figure(figsize=(11.2, 4.8))
    ax = plt.gca()
    plt.plot_date(x_dt, y_vals, "-", linewidth=2)  # plotting datetimes directly
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator())
    plt.grid(True, alpha=0.25)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.tight_layout()
    return _save_current_fig_to_bytes()

def _pick_top_keys(total_by_key: dict[str, float], k: int) -> list[str]:
    return [kk for kk, _ in sorted(total_by_key.items(), key=lambda kv: kv[1], reverse=True)[:k]]

async def send_quest_timeseries_chart(
    inter: discord.Interaction,
    payload: Any,
    *,
    area: Optional[str],
    interval_label: str,           # e.g., "last 24h"
    mode: str,                     # 'sum' | 'grouped' | 'surged'
    query_quest_mode: str = "all", # 'all' | 'AR' | 'NORMAL' (title only; server has already filtered)
    query_quest_type: str = "all", # QuestTaskType id string or 'all'
    title_prefix: str = "Quests • Time-Series",
) -> None:
    """
    Visuals for quests time-series (totals).
    - sum: sends total only.
    - grouped: line charts over time for totals + top breakdowns (quest_type, reward_poke, reward_item).
    - surged: bucketed 'hour N' bars (totals) + clustered bars for top quest types and top Pokémon.
    """
    title_base = f"{title_prefix} • {_format_title_suffix(area)} • {interval_label} • {query_quest_mode} • type={query_quest_type}"

    # ---------- SUM ----------
    if mode == "sum":
        total = 0.0
        for b in _iter_area_blocks(payload):
            if b.get("mode") != "sum": continue
            d = (b.get("data") or {})
            if isinstance(d.get("total"), (int, float)):
                total += float(d["total"])
        return await inter.followup.send(f"**Total quests** ({interval_label}, {query_quest_mode}, type={query_quest_type}): **{_fmt_compact(total)}**", ephemeral=True)

    # ---------- GROUPED ----------
    if mode == "grouped":
        blocks = [b for b in _iter_area_blocks(payload) if _is_quests_ts_grouped_payload(b)]
        if not blocks:
            return await _send_image(inter, _blank_image("No grouped time-series data"), title_base)

        merged = _collapse_ts_grouped(blocks)
        totals_by_ts: dict[int, float] = merged["totals_by_ts"]
        if not totals_by_ts:
            return await _send_image(inter, _blank_image("No time points"), title_base)

        # Totals line
        x = _sorted_epoch_list(totals_by_ts)
        y = [totals_by_ts[t] for t in x]
        img = _plot_simple_timeseries(x, y, f"{title_base} • totals")
        await _send_image(inter, img, f"{title_base} • totals", filename_slug="quests_ts_totals")

        # Top-N quest types (lines)
        by_qt: dict[str, dict[int, float]] = merged["by_qtype"]
        qt_totals = {qt: sum(series.values()) for qt, series in by_qt.items()}
        top_qt = _pick_top_keys(qt_totals, 6)
        if top_qt:
            plt.figure(figsize=(11.8, 5.0))
            ax = plt.gca()
            for qt in top_qt:
                series = by_qt[qt]
                xs = _sorted_epoch_list(series)
                if not xs: continue
                ys = [series[t] for t in xs]
                lbl = _quest_type_label(qt)
                # align to full x by reindex (sparse keys)
                mp = {t: series.get(t, 0.0) for t in x}
                ys_full = [mp[t] for t in x]
                x_dt_master = _epochs_to_datetimes(x)
                plt.plot_date(x_dt_master, ys_full, "-", linewidth=1.8, label=lbl)
            ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator())
            plt.grid(True, alpha=0.25)
            plt.ylabel("Count")
            plt.title(f"{title_base} • top quest types")
            if len(top_qt) <= 12:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title_base} • quest types", filename_slug="quests_ts_qtypes")

        # Top-N reward Pokémon (lines)
        by_pk: dict[str, dict[int, float]] = merged["by_poke"]
        pk_totals = {pk: sum(series.values()) for pk, series in by_pk.items() if pk != "None"}
        top_pk = _pick_top_keys(pk_totals, 8)
        if top_pk:
            plt.figure(figsize=(11.8, 5.0))
            ax = plt.gca()
            x_dt_master = _epochs_to_datetimes(x)
            for pk in top_pk:
                series = by_pk[pk]
                ys_full = [series.get(t, 0.0) for t in x]
                plt.plot_date(x_dt_master, ys_full, "-", linewidth=1.6, label=_poke_label_from_id(pk))
            ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator())
            plt.grid(True, alpha=0.25)
            plt.ylabel("Count")
            plt.title(f"{title_base} • top reward Pokémon")
            plt.legend(fontsize=8, ncols=2, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title_base} • reward pokémon", filename_slug="quests_ts_reward_poke")

        # Top-N reward items (lines)
        by_it: dict[str, dict[int, float]] = merged["by_item"]
        it_totals = {it: sum(series.values()) for it, series in by_it.items() if it != "None"}
        top_it = _pick_top_keys(it_totals, 6)
        if top_it:
            plt.figure(figsize=(11.8, 5.0))
            ax = plt.gca()
            x_dt_master = _epochs_to_datetimes(x)
            for it in top_it:
                series = by_it[it]
                ys_full = [series.get(t, 0.0) for t in x]
                plt.plot_date(x_dt_master, ys_full, "-", linewidth=1.6, label=_reward_item_label(it))
            ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(matplotlib.dates.AutoDateLocator())
            plt.grid(True, alpha=0.25)
            plt.ylabel("Count")
            plt.title(f"{title_base} • top reward items")
            plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title_base} • reward items", filename_slug="quests_ts_reward_items")

        return

    # ---------- SURGED (hourly buckets) ----------
    if mode == "surged":
        blocks = [b for b in _iter_area_blocks(payload) if isinstance(b, dict) and b.get("mode") == "surged"]
        if not blocks:
            return await _send_image(inter, _blank_image("No surged time-series data"), title_base)

        merged = _collapse_ts_surged(blocks)
        totals_by_hour: dict[str, float] = merged["totals_by_hour"]
        if not totals_by_hour:
            return await _send_image(inter, _blank_image("Empty surged data"), title_base)

        # Sort hours like "hour 0", "hour 1", ...
        def _hnum(h: str) -> int:
            try:
                return int(str(h).split()[-1])
            except Exception:
                return 0
        hrs = sorted(totals_by_hour.keys(), key=_hnum)
        vals = [totals_by_hour[h] for h in hrs]

        # Chart 1: totals per hour (bar)
        plt.figure(figsize=(11.2, 4.6))
        ax = plt.gca()
        bars = plt.bar(hrs, vals)
        _annotate_bars(ax, bars, vals)
        plt.ylabel("Count")
        plt.title(f"{title_base} • surged • totals by hour")
        img = _save_current_fig_to_bytes()
        await _send_image(inter, img, f"{title_base} • surged totals", filename_slug="quests_ts_surged_totals")

        # Chart 2: clustered bars for top quest types across hours
        by_qh: dict[str, dict[str, float]] = merged["by_qtype_hour"]
        qt_totals = {qt: sum(series.values()) for qt, series in by_qh.items()}
        top_qt = _pick_top_keys(qt_totals, 6)
        if top_qt:
            idx = list(range(len(hrs)))
            n_series = max(1, len(top_qt))
            width = 0.8 / n_series

            plt.figure(figsize=(11.8, 5.0))
            ax = plt.gca()
            for i, qt in enumerate(top_qt):
                series = by_qh.get(qt, {})
                y = [series.get(h, 0.0) for h in hrs]
                offs = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offs, y, width=width, label=_quest_type_label(qt))
                _annotate_bars(ax, bars, y)
            plt.xticks(idx, hrs, rotation=0)
            plt.ylabel("Count")
            plt.title(f"{title_base} • surged • top quest types")
            if len(top_qt) <= 12:
                plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title_base} • surged quest types", filename_slug="quests_ts_surged_qtypes")

        # Chart 3: clustered bars for top reward pokémon across hours
        by_ph: dict[str, dict[str, float]] = merged["by_poke_hour"]
        pk_totals = {pk: sum(series.values()) for pk, series in by_ph.items() if pk != "None"}
        top_pk = _pick_top_keys(pk_totals, 6)
        if top_pk:
            idx = list(range(len(hrs)))
            n_series = max(1, len(top_pk))
            width = 0.8 / n_series

            plt.figure(figsize=(11.8, 5.0))
            ax = plt.gca()
            for i, pk in enumerate(top_pk):
                series = by_ph.get(pk, {})
                y = [series.get(h, 0.0) for h in hrs]
                offs = [x - 0.4 + i * width + width / 2 for x in idx]
                bars = plt.bar(offs, y, width=width, label=_poke_label_from_id(pk))
                _annotate_bars(ax, bars, y)
            plt.xticks(idx, hrs, rotation=0)
            plt.ylabel("Count")
            plt.title(f"{title_base} • surged • top reward Pokémon")
            plt.legend(fontsize=8, ncols=3, loc="upper left")
            img = _save_current_fig_to_bytes()
            await _send_image(inter, img, f"{title_base} • surged reward pokémon", filename_slug="quests_ts_surged_poke")

        return

    # ---------- fallback ----------
    return await _send_image(inter, _blank_image(f"Unsupported mode '{mode}'"), title_base)
