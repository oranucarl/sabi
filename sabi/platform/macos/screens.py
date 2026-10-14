"""Screen capture with the geometry needed to map model coordinates back to the screen.

Three coordinate spaces are involved:
- image space: the downscaled JPEG the model sees,
- screen points: Quartz/Qt global coordinates (top-left origin, logical points, not Retina pixels),
- physical pixels: what the display actually has (2× points on Retina).

The model only ever sees and answers in image space; the prompt states the image size. Qwen2.5-VL
is trained on absolute pixel coordinates of its input image, and Claude handles them well too.
Retina scale never leaks into prompts.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import mss
from PIL import Image

MAX_WIDTH = 1024
JPEG_QUALITY = 75


@dataclass(frozen=True)
class Shot:
    jpeg_b64: str
    left: float  # screen points
    top: float
    width: float
    height: float
    image_width: int  # downscaled pixels
    image_height: int

    def to_screen(self, x: float, y: float) -> tuple[float, float]:
        """Map a pixel coordinate in the downscaled image to global screen points."""
        fx = min(max(x / self.image_width, 0.0), 1.0)
        fy = min(max(y / self.image_height, 0.0), 1.0)
        return self.left + fx * self.width, self.top + fy * self.height


def capture_screen_at(x: float, y: float) -> Shot:
    """Capture the display containing the point (x, y), falling back to the main display."""
    with mss.mss() as sct:
        monitors = sct.monitors[1:]
        target = monitors[0]
        for mon in monitors:
            if mon["left"] <= x < mon["left"] + mon["width"] and mon["top"] <= y < mon["top"] + mon["height"]:
                target = mon
                break
        raw = sct.grab(target)
        image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    if image.width > MAX_WIDTH:
        image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return Shot(
        jpeg_b64=base64.b64encode(buf.getvalue()).decode("ascii"),
        left=target["left"],
        top=target["top"],
        width=target["width"],
        height=target["height"],
        image_width=image.width,
        image_height=image.height,
    )
