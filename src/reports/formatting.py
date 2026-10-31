"""Visual styling, color definitions, and accessibility helpers."""

from typing import Tuple
from docx.shared import RGBColor


# Hex color codes for HTML email inline CSS
HEX_RED = "#D32F2F"      # Drop alerts, issues, needs attention
HEX_GREEN = "#2E7D32"    # Positive change, above baseline/target
HEX_BLUE = "#1976D2"     # Neutral headers, metadata, section titles
HEX_GRAY = "#555555"     # Secondary labels, subtitles
HEX_LIGHT_BG = "#F8F9FA" # Table header background
HEX_BORDER = "#E0E0E0"   # Table borders

# RGBColor objects for python-docx
RGB_RED = RGBColor(211, 47, 47)
RGB_GREEN = RGBColor(46, 125, 50)
RGB_BLUE = RGBColor(25, 118, 210)
RGB_GRAY = RGBColor(85, 85, 85)
RGB_BLACK = RGBColor(30, 30, 30)


def format_delta_text(
    delta_val: float,
    unit: str = "%",
    is_lower_bad: bool = True,
    threshold: float = 0.0,
) -> Tuple[str, str, RGBColor]:
    """Format numeric change with sign, text label, and color.
    
    Returns (formatted_text, hex_color, rgb_color).
    Ensures accessibility by including explicit +/- signs and text labels.
    """
    sign = "+" if delta_val > 0 else ""
    if unit == "%":
        val_str = f"{sign}{delta_val:.1f}%"
    elif unit == "$":
        val_str = f"{sign}${abs(delta_val):,.2f}" if delta_val < 0 else f"{sign}${delta_val:,.2f}"
    else:
        val_str = f"{sign}{delta_val:,.0f} {unit}"

    if delta_val < threshold:
        label = f"{val_str} [Needs attention]"
        hex_color = HEX_RED
        rgb_color = RGB_RED
    elif delta_val > threshold:
        label = f"{val_str} [Ahead]"
        hex_color = HEX_GREEN
        rgb_color = RGB_GREEN
    else:
        label = f"{val_str} [Normal]"
        hex_color = HEX_BLUE
        rgb_color = RGB_BLUE

    return label, hex_color, rgb_color

