import discord
from core.dragonite.sql.dao import IntervalUnit

# ---------- Discord User Tracker ----------
def _actor(inter: discord.Interaction) -> str:
    """Return 'DisplayName#1234 (123456789012345678)' for logs."""
    u = inter.user
    # If you prefer username only, use: f"{u} ({u.id})"
    return f"{getattr(u, 'display_name', str(u))} ({u.id})"

# ---------- Pretty helpers ----------
def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)

def _fmt_pct(n: float) -> str:
    return f"{n:.0f}%"

def _fmt_ts(epoch: int | None) -> str:
    try:
        e = int(epoch or 0)
        return f"<t:{e}:R>" if e > 0 else "—"
    except Exception:
        return "—"

def _safe_div(n: float, d: float) -> float:
    return (n / d * 100.0) if d else 0.0

def _bar_stacked(parts: list[tuple[int, str]], total: int, length: int = 24) -> str:
    """
    parts: [(count, emoji), ...] in draw order
    total: denominator for proportions
    """
    if total <= 0:
        return "⬜" * length
    # initial proportional lengths
    raw = [(c, int(round((c / total) * length))) for c, _ in parts]
    alloc = sum(l for _, l in raw)
    # fix rounding so sum == length
    i = 0
    while alloc > length and any(l > 0 for _, l in raw):
        c, l = raw[i]
        if l > 0:
            raw[i] = (c, l - 1); alloc -= 1
        i = (i + 1) % len(raw)
    i = 0
    while alloc < length:
        c, l = raw[i]
        raw[i] = (c, l + 1); alloc += 1
        i = (i + 1) % len(raw)
    # render
    out = []
    for (_, l), (_, emoji) in zip(raw, parts):
        out.append(emoji * l)
    return "".join(out)

def _bar_green(current: int, total: int, length: int = 14) -> str:
    if total <= 0:
        return "⬜" * length
    ratio = max(0.0, min(1.0, current / total))
    full = int(round(ratio * length))
    return "🟩" * full + "⬜" * (length - full)

# ADD this near the other bar helpers

def _bar_enc_gmo(enc: int, gmo: int, length: int = 18) -> str:
    """
    Blue (🟦) for Encounter, Yellow (🟨) for GMO — stacked bar.
    """
    enc = max(0, int(enc or 0))
    gmo = max(0, int(gmo or 0))
    total = enc + gmo
    if total <= 0:
        return "⬜" * length
    return _bar_stacked([(enc, "🟦"), (gmo, "🟨")], total, length)


def _bar_good_bad(good: int, bad: int, length: int = 18) -> str:
    total = max(0, good) + max(0, bad)
    if total <= 0:
        return "⬜" * length
    good_len = int(round((good / total) * length))
    bad_len  = int(round((bad  / total) * length))
    # fit exactly
    while good_len + bad_len > length:
        if bad_len > good_len and bad_len > 0:
            bad_len -= 1
        elif good_len > 0:
            good_len -= 1
        else:
            break
    while good_len + bad_len < length:
        if good_len <= bad_len:
            good_len += 1
        else:
            bad_len += 1
    return "🟩" * good_len + "🟥" * bad_len

def _yn(v: bool) -> str:
    return "✅ Yes" if bool(v) else "❌ No"

def _flag(name: str, v: bool) -> str:
    return f"{'🟥' if v else '⬜'} {name}"

def _maybe(v) -> str:
    return "—" if v in (None, "", 0, False) else str(v)


def _health_color(active: int, expected: int) -> int:
    pct = _safe_div(active, expected)
    if pct >= 90:
        return 0x3BA55D  # green
    if pct >= 60:
        return 0xFEE75C  # yellow
    if pct >= 30:
        return 0xFAA61A  # orange
    return 0xED4245      # red

def _shorten(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[:limit-1] + "…"

# ---------- Builders ----------
def _fmt_modes_field(modes: dict, top_n: int = 6) -> str:
    if not modes:
        return "—"
    items = [(m, d.get("workers", 0)) for m, d in modes.items()]
    items.sort(key=lambda x: x[1], reverse=True)

    top = items[:top_n]
    rest = items[top_n:]

    lines = [f"• **{m}** — {_fmt_int(w)} worker(s)" for m, w in top]
    if rest:
        total_rest = sum(w for _, w in rest)
        lines.append(f"• **+{len(rest)} more** — {_fmt_int(total_rest)} worker(s)")
    return _shorten("\n".join(lines))

def _fmt_providers_block(summary: dict) -> str:
    provs = summary.get("providers", {})
    if not provs:
        return "—"
    lines = []
    for p, d in sorted(provs.items()):
        total = int(d.get("total", 0) or 0)
        good = int(d.get("good", 0) or 0)
        bad  = int(d.get("bad", 0) or 0)
        pct  = _safe_div(good, total)
        bar  = _bar_good_bad(good, bad, length=12)
        lines.append(f"**{p}**  {bar}  {_fmt_pct(pct)}  (G:{_fmt_int(good)} / T:{_fmt_int(total)})")
    return _shorten("\n".join(lines))

# ---------- Helpers for Areas in Core ----------
def _on_off(v: bool) -> str:
    return "On" if v else "Off"

def _yes_no(v: bool) -> str:
    return "Yes" if v else "No"

# -------- Helpers for SQL Dragonite ----------
_INTERVAL_ALIASES = {
    "m": IntervalUnit.MINUTE, "min": IntervalUnit.MINUTE, "minute": IntervalUnit.MINUTE, "minutes": IntervalUnit.MINUTE,
    "h": IntervalUnit.HOUR,   "hr": IntervalUnit.HOUR,    "hour": IntervalUnit.HOUR,     "hours": IntervalUnit.HOUR,
    "d": IntervalUnit.DAY,    "day": IntervalUnit.DAY,    "days": IntervalUnit.DAY,
    "mo": IntervalUnit.MONTH, "mon": IntervalUnit.MONTH,  "month": IntervalUnit.MONTH,   "months": IntervalUnit.MONTH,
}

def _parse_interval_unit(s: str) -> IntervalUnit:
    key = (s or "").strip().lower()
    if key in _INTERVAL_ALIASES:
        return _INTERVAL_ALIASES[key]
    # strict fallback to raise like DAO does
    return IntervalUnit(key)  # will raise ValueError if not valid

def _parse_usernames_block(s: str) -> list[str]:
    # accepts comma, space or newline separated
    raw = (s or "").replace(",", " ").split()
    # unique, keep order
    seen, out = set(), []
    for u in raw:
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

def _parse_hours_list(s: str) -> list[int]:
    """Parse '0 11' or '0,11' (or mixed) into [0, 11]."""
    tokens = (s or "").replace(",", " ").split()
    hours: list[int] = []
    for t in tokens:
        if not t.strip():
            continue
        hours.append(int(t))  # let DAO range-check; this only enforces int-cast
    return hours
