# -*- coding: utf-8 -*-
"""生成桌面应用图标：assets/icon.ico（Windows）与 assets/icon.icns（macOS）。

在无现成设计稿的情况下，用 Pillow 程序化绘制一枚简洁图标：
深色圆角方形背景 + 橙→绿渐变的跑步轨迹折线（沿途点缀 GPS 采样点，
末端以带白描边的大圆点标记终点）。所有几何坐标均为 0~1 的归一化值，
可按任意目标尺寸直接重绘，保证各尺寸下线条清晰而非缩放模糊。

用法（开发工具，依赖 Pillow，不进入运行时依赖）：
    python scripts/make_icon.py                  # 程序化绘制并写出 assets/icon.ico
    python scripts/make_icon.py --source xx.png  # 以现有图片为底（居中裁正方形、抠白底）
    python scripts/make_icon.py --ico-source assets/icon.ico
        # 以现有 ICO 最大帧（含既有抠底等处理效果）为母版重建全部尺寸，
        # 用于更新设计后统一各平台/各尺寸视觉

macOS 的 Dock 图标来自 .app bundle 的 .icns；iconutil 仅存在于 macOS，
非 darwin 平台自动跳过 icns 生成。
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "assets" / "icon.ico"
DEFAULT_OUTPUT_ICNS = PROJECT_ROOT / "assets" / "icon.icns"

BASE_SIZE = 256
ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))

# iconset 标准命名（pt 尺寸 → 实际像素），@2x 为 Retina 倍率
ICNS_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)

# 抠白底判定：RGB 三通道均不低于该阈值视为背景白
WHITE_THRESHOLD = 240

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


def _cutout_white_background(rgba: Image.Image) -> Image.Image:
    """将边缘连通的近白色区域置为透明（泛洪填充）。

    只抠掉与图片边缘连通的白色，主体内部的白色（如鞋面反光）保留。
    alpha 先用 MinFilter(3) 轻微收缩 1px，削掉缩放后残留的白色镶边。
    """
    width, height = rgba.size
    rgb = rgba.convert("RGB")
    pixels = rgb.load()

    def is_white(x: int, y: int) -> bool:
        r, g, b = pixels[x, y]
        return r >= WHITE_THRESHOLD and g >= WHITE_THRESHOLD and b >= WHITE_THRESHOLD

    visited = bytearray(width * height)
    stack = []
    for x in range(width):
        for y in (0, height - 1):
            if is_white(x, y) and not visited[y * width + x]:
                visited[y * width + x] = 1
                stack.append((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if is_white(x, y) and not visited[y * width + x]:
                visited[y * width + x] = 1
                stack.append((x, y))

    while stack:
        x, y = stack.pop()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                idx = ny * width + nx
                if not visited[idx] and is_white(nx, ny):
                    visited[idx] = 1
                    stack.append((nx, ny))

    mask = Image.frombytes("L", (width, height), bytes(255 - 255 * v for v in visited))
    mask = mask.filter(ImageFilter.MinFilter(3))
    out = rgba.copy()
    out.putalpha(mask)
    return out


def prepare_source(source_path: Path) -> Image.Image:
    """读取源图：居中裁正方形并抠白底，返回全分辨率 RGBA。"""
    with Image.open(source_path) as src:
        rgba = src.convert("RGBA")
    side = min(rgba.size)
    left = (rgba.width - side) // 2
    top = (rgba.height - side) // 2
    return _cutout_white_background(rgba.crop((left, top, left + side, top + side)))


def prepare_from_ico(ico_path: Path) -> Image.Image:
    """以现有 ICO 的最大尺寸帧为母版（含既有的抠底等处理效果）。

    用于沿用已提交 assets/icon.ico 中的现成设计（其处理逻辑未必能由
    源图复现），各目标尺寸均由该帧 LANCZOS 缩放。
    """
    with Image.open(ico_path) as ico:
        ico.size = max(ico.ico.sizes())
        ico.load()
        return ico.copy().convert("RGBA")


def save_ico(frames: dict[int, Image.Image], output_path: Path) -> None:
    """将以各尺寸预生成的帧写入 ICO 文件。

    帧由调用方按同一来源生成（程序化逐尺寸重绘 / 源图逐尺寸缩放），
    保证各尺寸视觉一致。
    """
    base_image = frames[BASE_SIZE]
    base_image.save(
        output_path,
        format="ICO",
        sizes=list(ICO_SIZES),
        append_images=[frames[size] for size, _ in ICO_SIZES if (size, size) != base_image.size],
    )


def save_icns(frame_builder, output_path: Path) -> None:
    """以 iconset 目录 + iconutil 生成 ICNS（仅 macOS 可用）。

    frame_builder 接收像素尺寸、返回对应 RGBA 帧，与 ICO 共用同一来源，
    保证两个平台各尺寸视觉一致。
    """
    with tempfile.TemporaryDirectory(suffix=".iconset") as tmp:
        iconset_dir = Path(tmp)
        for filename, size in ICNS_SIZES:
            frame_builder(size).save(iconset_dir / filename, format="PNG")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_path)],
            check=True,
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成 assets/icon.ico 与 assets/icon.icns（多尺寸桌面图标）")
    parser.add_argument("--source", type=Path, default=None, help="可选：以现有图片为底（居中裁正方形、抠白底）")
    parser.add_argument(
        "--ico-source",
        type=Path,
        default=None,
        help="可选：以现有 ICO 最大帧为母版（沿用其中已有的处理效果），与 --source 互斥",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 ICO 路径，默认 assets/icon.ico")
    parser.add_argument(
        "--output-icns",
        type=Path,
        default=DEFAULT_OUTPUT_ICNS,
        help="输出 ICNS 路径，默认 assets/icon.icns（仅 macOS 生成）",
    )
    args = parser.parse_args()

    if args.source and args.ico_source:
        parser.error("--source 与 --ico-source 互斥，只能选一个")

    # 帧工厂：源图模式先全分辨率抠白底再逐尺寸缩放（抠除只做一次）；
    # ICO 母版模式同理直接缩放；程序化模式按归一化坐标逐尺寸重绘，
    # 避免小尺寸缩放模糊
    if args.source:
        prepared = prepare_source(args.source)
        frame_builder = lambda size: prepared.resize((size, size), Image.LANCZOS)  # noqa: E731
    elif args.ico_source:
        master = prepare_from_ico(args.ico_source)
        frame_builder = lambda size: master.resize((size, size), Image.LANCZOS)  # noqa: E731
    else:
        frame_builder = build_icon
    frames = {size: frame_builder(size) for size, _ in ICO_SIZES}

    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_ico(frames, output_path)

    with Image.open(output_path) as ico:
        written = sorted(ico.ico.sizes())
    print(f"已生成: {output_path}")
    print(f"文件大小: {output_path.stat().st_size} 字节")
    print(f"包含尺寸: {written}")

    if sys.platform == "darwin":
        icns_path = args.output_icns if args.output_icns.is_absolute() else PROJECT_ROOT / args.output_icns
        icns_path.parent.mkdir(parents=True, exist_ok=True)
        save_icns(frame_builder, icns_path)
        print(f"已生成: {icns_path}")
        print(f"文件大小: {icns_path.stat().st_size} 字节")
        print(f"包含尺寸: {', '.join(f'{px}px' for _, px in ICNS_SIZES)}")
    else:
        print("非 macOS 平台，跳过 ICNS 生成（iconutil 不可用）")


if __name__ == "__main__":
    main()
