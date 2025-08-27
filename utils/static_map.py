from __future__ import annotations
from typing import List, Dict, Tuple
import math
import plotly.graph_objects as go

Coord = Dict[str, float]  # {"lat": float, "lon": float}

def _close_ring(points: List[Coord]) -> Tuple[List[float], List[float]]:
    if not points:
        return [], []
    lat = [float(p["lat"]) for p in points]
    lon = [float(p["lon"]) for p in points]
    if points[0] != points[-1]:
        lat.append(lat[0]); lon.append(lon[0])
    return lat, lon

def _center(points: List[Coord]) -> Tuple[float, float]:
    lats = [float(p["lat"]) for p in points]
    lons = [float(p["lon"]) for p in points]
    return sum(lats)/len(lats), sum(lons)/len(lons)

def _compute_zoom_for_bounds(min_lat, max_lat, min_lon, max_lon, width_px, height_px, pad_ratio=0.30) -> float:
    """
    Approximate WebMercator zoom that fits the bbox into width/height with padding.
    Works with Plotly (tile size 256). Returns a float zoom.
    """
    # prevent zero spans
    lat_span = max(1e-7, (max_lat - min_lat))
    lon_span = max(1e-7, (max_lon - min_lon))

    # usable pixels after padding on each side
    usable_w = max(1.0, width_px * (1.0 - 2.0 * pad_ratio))
    usable_h = max(1.0, height_px * (1.0 - 2.0 * pad_ratio))

    # adjust longitude span by cos(latitude) (Mercator horizontal shrinking)
    mid_lat_rad = math.radians((min_lat + max_lat) / 2.0)
    lon_span_eff = lon_span * math.cos(mid_lat_rad)
    lon_span_eff = max(1e-9, lon_span_eff)

    # Degrees per pixel at zoom z: 360 / (256 * 2^z) horizontally
    # Solve for z using horizontal and vertical independently, then pick the min (tighter)
    # Horizontal:
    deg_per_px_w = lon_span_eff / usable_w
    z_w = math.log2(360.0 / (256.0 * deg_per_px_w))

    # Vertical: use 180 deg total (pole-to-pole) approx in degrees-per-pixel
    deg_per_px_h = lat_span / usable_h
    z_h = math.log2(180.0 / (256.0 * deg_per_px_h))

    z = min(z_w, z_h)
    # clamp to reasonable Mapbox zooms
    return float(max(1.0, min(19.5, z)))

def render_geofence_png(geofence: List[Coord], width: int = 900, height: int = 540, pad_ratio: float = 0.30) -> tuple[bytes, str]:
    """
    Render geofence over OpenStreetMap tiles with Plotly Scattermapbox.
    Requires: plotly, kaleido. Returns (png_bytes, "geofence.png").
    """
    if not geofence:
        raise ValueError("Empty geofence")

    lat, lon = _close_ring(geofence)
    center_lat, center_lon = _center(geofence)

    min_lat, max_lat = min(lat), max(lat)
    min_lon, max_lon = min(lon), max(lon)

    zoom = _compute_zoom_for_bounds(min_lat, max_lat, min_lon, max_lon, width, height, pad_ratio=pad_ratio)

    fig = go.Figure(go.Scattermapbox(
        lat=lat,
        lon=lon,
        mode="lines",
        fill="toself",
        line=dict(width=3, color="#3BA55D"),
        fillcolor="rgba(59,165,93,0.25)",
        hoverinfo="skip",
        name="Geofence",
    ))

    fig.update_layout(
        width=width, height=height,
        paper_bgcolor="#1e1f22",
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
        title=dict(text="Geofence", x=0.5, font=dict(color="white")),
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom,
        ),
    )

    try:
        png = fig.to_image(format="png", engine="kaleido", width=width, height=height, scale=1)
    except Exception as e:
        if "kaleido" in str(e).lower():
            raise RuntimeError("Plotly static export requires 'kaleido' (pip install kaleido)") from e
        raise
    return png, "geofence.png"
