"""生成 voiceinput.ico（打包 exe 用的图标）。用法：python -m voiceinput.make_icon"""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

from .config import PROJECT_ROOT


def draw_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size
    stroke = max(2, int(s * 0.055))

    # 圆形底
    d.ellipse((s * 0.03, s * 0.03, s * 0.97, s * 0.97), fill=(52, 120, 246))
    white = (255, 255, 255)
    # 麦克风头
    d.rounded_rectangle((s * 0.36, s * 0.19, s * 0.64, s * 0.55), radius=int(s * 0.14), fill=white)
    # 支架弧
    d.arc((s * 0.26, s * 0.30, s * 0.74, s * 0.72), start=0, end=180, fill=white, width=stroke)
    # 竖杆 + 底座
    d.line((s * 0.50, s * 0.71, s * 0.50, s * 0.82), fill=white, width=stroke)
    d.line((s * 0.39, s * 0.82, s * 0.61, s * 0.82), fill=white, width=stroke)
    return img


def main() -> int:
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    out = PROJECT_ROOT / "voiceinput.ico"
    draw_icon(256).save(out, sizes=sizes)
    print(f"已生成图标：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
