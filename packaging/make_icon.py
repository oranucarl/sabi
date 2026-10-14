"""Draw SAbi's app icon and write an .icns file. Usage: python make_icon.py <out.icns>"""

import sys

from PIL import Image, ImageDraw, ImageFont

GREEN = (0, 135, 81)
WHITE = (255, 255, 255)


def draw(size: int) -> Image.Image:
    s = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # macOS icon grid: rounded square inset from the canvas edge.
    d.rounded_rectangle([100 * s, 100 * s, 924 * s, 924 * s], radius=185 * s, fill=GREEN)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/SFNSRounded.ttf", int(470 * s))
    except OSError:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(470 * s))
    d.text((470 * s, 520 * s), "S", font=font, fill=WHITE, anchor="mm")
    # The pointer buddy, top-right, tip pointing up-left.
    tip = (650 * s, 230 * s)
    d.polygon([tip, (680 * s, 420 * s), (720 * s, 360 * s), (790 * s, 350 * s)], fill=WHITE)
    return img


def main(out: str) -> None:
    # Pillow writes all standard representations into the ICNS file. This avoids iconutil's
    # stricter iconset validation changing between macOS releases.
    draw(1024).save(out, format="ICNS")


if __name__ == "__main__":
    main(sys.argv[1])
