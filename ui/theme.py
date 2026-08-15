from __future__ import annotations

COLORS = {
    "background": "#F4F6F8", "surface": "#FFFFFF", "navigation": "#0B2235",
    "primary": "#123D63", "accent": "#58B719", "text": "#17212B",
    "muted": "#667085", "border": "#D8DEE6", "success": "#16834A",
    "warning": "#D97706", "error": "#C93C37", "inactive": "#64748B",
    "pressure": "#123D63", "flow": "#16834A",
}

SPACING = {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32}
RADII = {"control": 4, "card": 6, "pill": 10}
def icon_path(name: str) -> str:
    from ui.resources import resource_path
    return str(resource_path("ui", "icons", f"{name}.svg"))
