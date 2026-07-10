"""
╔══════════════════════════════════════════════════╗
║  crop_circle.py                                  ║
║  将 favicon.png 裁剪为正圆形，输出到             ║
║  favicon_circle.png (透明背景 PNG)               ║
╚══════════════════════════════════════════════════╝

用法:
    python scripts/crop_circle.py
"""

from pathlib import Path
from PIL import Image, ImageDraw

def crop_to_circle(input_path: str, output_path: str) -> None:
    """
    将图像裁剪为正圆形（透明背景）。
    
    步骤:
        1. 加载原图
        2. 取 min(宽,高) 作为圆的直径，从中心裁出正方形
        3. 创建圆形 alpha 遮罩
        4. 应用遮罩并保存 PNG
    """
    img = Image.open(input_path).convert("RGBA")
    w, h = img.size

    # 1. 中心裁剪为正方形
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    square = img.crop((left, top, left + side, top + side))

    # 2. 创建圆形遮罩
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, side - 1, side - 1), fill=255)

    # 3. 应用遮罩
    result = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    result.paste(square, (0, 0), mask)

    # 4. 保存
    result.save(output_path, "PNG")
    print(f"✅ 裁剪完成: {output_path}")
    print(f"   尺寸: {side}×{side}  (原图: {w}×{h})")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    crop_to_circle(str(root / "favicon.png"), str(root / "favicon_circle.png"))
