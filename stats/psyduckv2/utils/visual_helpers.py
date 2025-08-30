from __future__ import annotations
import json
import os
import io
from typing import Optional
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

