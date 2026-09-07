# -*- coding: utf-8 -*-
"""生成 Windows 桌面应用图标 assets/icon.ico。

在无现成设计稿的情况下，用 Pillow 程序化绘制一枚简洁图标：
深色圆角方形背景 + 橙→绿渐变的跑步轨迹折线（沿途点缀 GPS 采样点，
末端以带白描边的大圆点标记终点）。所有几何坐标均为 0~1 的归一化值，
可按任意目标尺寸直接重绘，保证各 ICO 尺寸下线条清晰而非缩放模糊。

用法（开发工具，依赖 Pillow，不进入运行时依赖）：
    python scripts/make_icon.py                  # 程序化绘制并写出 assets/icon.ico
    python scripts/make_icon.py --source xx.png  # 以现有图片为底（居中裁正方形）
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "assets" / "icon.ico"

BASE_SIZE = 256
ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))

# 背景垂直渐变（上 → 下），深蓝灰石墨色，深浅背景下均可辨识
BG_TOP = (36, 44, 60, 255)
BG_BOTTOM = (16, 21, 33, 255)
CORNER_RADIUS_RATIO = 0.22  # 圆角半径占边长比例

# 轨迹配色：起点橙 → 终点亮绿
TRACK_START = (255, 140, 62, 255)
TRACK_END = (116, 226, 84, 255)
POINT_COLOR = (255, 255, 255, 235)

# 轨迹形状：两段三次贝塞尔（控制点/端点均为归一化坐标），左下蜿蜒至右上
_BEZIER_SEGS = (
    ((0.18, 0.78), (0.36, 0.90), (0.16, 0.48), (0.44, 0.44)),
    ((0.44, 0.44), (0.68, 0.40), (0.50, 0.18), (0.80, 0.26)),
)
_BEZIER_SAMPLES_PER_SEG = 28  # 每段采样点数，保证折线足够平滑


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    samples: int,
) -> list[tuple[float, float]]:
    """对一段三次贝塞尔曲线均匀采样，返回像素坐标点列表。"""
    points = []
    for i in range(samples + 1):
        t = i / samples
        mt = 1.0 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def _track_points(size: int) -> list[tuple[int, int]]:
    """计算整条轨迹在给定尺寸下的像素坐标点列表。"""
    points = []
    for p0, p1, p2, p3 in _BEZIER_SEGS:
        seg = _cubic_bezier(p0, p1, p2, p3, _BEZIER_SAMPLES_PER_SEG)
        points.extend(seg if not points else seg[1:])
    return [(round(x * size), round(y * size)) for x, y in points]


def _lerp_color(
    start: tuple[int, int, int, int], end: tuple[int, int, int, int], ratio: float
) -> tuple[int, int, int, int]:
    """按比例在两个 RGBA 颜色间线性插值。"""
    return tuple(round(s + (e - s) * ratio) for s, e in zip(start, end))  # type: ignore[return-value]


def _dot(draw: ImageDraw.ImageDraw, center: tuple[float, float], radius: float, **kwargs) -> None:
    """绘制实心圆。Pillow 的 ellipse 无抗锯齿，小半径会畸变成十字/菱形，radius<=2 时用方块近似。"""
    cx, cy = center
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    if radius <= 2:
        draw.rectangle(box, **kwargs)
    else:
        draw.ellipse(box, **kwargs)


def _heading(start: tuple[int, int], end: tuple[int, int]) -> float:
    """两采样点间的行进方向角（弧度）。"""
    return math.atan2(end[1] - start[1], end[0] - start[0])


def _turn_angle(prev_seg: float, next_seg: float) -> float:
    """相邻两段的转角绝对值（弧度，0~pi）。"""
    return abs(math.remainder(prev_seg - next_seg, 2 * math.pi))


def _draw_background(canvas: Image.Image, size: int) -> None:
    """绘制带圆角的深色垂直渐变背景。"""
    radius = round(size * CORNER_RADIUS_RATIO)
    gradient = Image.new("RGBA", (size, size))
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(size):
        grad_draw.line([(0, y), (size, y)], fill=_lerp_color(BG_TOP, BG_BOTTOM, y / size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    canvas.paste(gradient, (0, 0), mask)


def _draw_track(canvas: Image.Image, size: int) -> None:
    """绘制渐变轨迹折线、起点/沿途采样点与终点标记。"""
    draw = ImageDraw.Draw(canvas)
    points = _track_points(size)
    line_width = max(1, round(size * 0.078))
    last = len(points) - 1

    # 逐段绘制并按弧长比例插值颜色；仅在转角超过阈值处补圆头，
    # 避免直线段上出现串珠状突起，同时防止急弯处线段脱节
    corner_threshold = 0.12  # 弧度，约 7 度
    for i in range(last):
        current, nxt = points[i], points[i + 1]
        color = _lerp_color(TRACK_START, TRACK_END, i / last)
        draw.line([current, nxt], fill=color, width=line_width)
        if 0 < i + 1 < last:
            turn = _turn_angle(_heading(current, nxt), _heading(nxt, points[i + 2]))
            if turn > corner_threshold:
                _dot(draw, nxt, line_width // 2, fill=color)

    # 起点：小实心白点（GPS 起标记）
    _dot(draw, points[0], max(1, round(size * 0.032)), fill=POINT_COLOR)

    # 沿途 GPS 采样点：仅在大尺寸绘制——小尺寸下点径与线宽接近，只会呈"+"形噪点
    if size >= 64:
        dot_radius = max(1, round(size * 0.022))
        for idx in (round(last / 3), round(last * 2 / 3)):
            _dot(draw, points[idx], dot_radius, fill=POINT_COLOR)

    # 终点：大尺寸为白描边圆点；小尺寸白描边会畸变成条纹，改用更大的实心绿点
    ex, ey = points[last]
    if size <= 48:
        end_radius = max(1, round(size * 0.070))
        _dot(draw, (ex, ey), end_radius, fill=TRACK_END)
    else:
        end_radius = max(2, round(size * 0.070))
        draw.ellipse(
            [ex - end_radius, ey - end_radius, ex + end_radius, ey + end_radius],
            fill=TRACK_END,
            outline=POINT_COLOR,
            width=max(1, round(size * 0.022)),
        )


def build_icon(size: int) -> Image.Image:
    """按指定尺寸绘制图标底图，返回 RGBA Image。"""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _draw_background(canvas, size)
    _draw_track(canvas, size)
    return canvas


def build_from_source(source_path: Path, size: int) -> Image.Image:
    """以现有图片为底：居中裁正方形后缩放到目标尺寸。"""
    with Image.open(source_path) as src:
        rgba = src.convert("RGBA")
    side = min(rgba.size)
    left = (rgba.width - side) // 2
    top = (rgba.height - side) // 2
    return rgba.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)


def save_ico(base_image: Image.Image, output_path: Path) -> dict[tuple[int, int], Image.Image]:
    """将底图以多尺寸形式写入 ICO 文件，返回各尺寸对应的帧。"""
    # 各尺寸均按归一化坐标直接重绘，避免小尺寸缩放导致线条模糊
    frames = {size: base_image if size == base_image.size else build_icon(size[0]) for size in ICO_SIZES}
    base_image.save(
        output_path,
        format="ICO",
        sizes=list(ICO_SIZES),
        append_images=[frames[size] for size in ICO_SIZES if size != base_image.size],
    )
    return frames


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成 assets/icon.ico（多尺寸 Windows 图标）")
    parser.add_argument("--source", type=Path, default=None, help="可选：以现有图片为底（居中裁正方形）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 ICO 路径，默认 assets/icon.ico")
    args = parser.parse_args()

    base = build_from_source(args.source, BASE_SIZE) if args.source else build_icon(BASE_SIZE)
    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_ico(base, output_path)

    with Image.open(output_path) as ico:
        written = sorted(ico.ico.sizes())
    size_bytes = output_path.stat().st_size
    print(f"已生成: {output_path}")
    print(f"文件大小: {size_bytes} 字节")
    print(f"包含尺寸: {written}")


if __name__ == "__main__":
    main()
