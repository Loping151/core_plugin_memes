"""纯 PIL 渲染——warm editorial dark 风格。

设计基调：
- 深墨色画布（带一点暖调）+ 米白正文 + 金色作为唯一明亮强调，sage/rose/mauve
  仅用作三种状态的语义色
- 字体：Noto Serif CJK Bold 作大标题，Noto Sans CJK Regular 作正文，
  JetBrains Mono 作命令/数字（找不到时层层降级到 wqy / DejaVu / PIL 默认）
- 几乎全部用细的金色 hairline 做版面切分；不用阴影、渐变这类容易"AI 风"的装饰

三个公开函数：
- `render_command_help`  插件命令帮助
- `render_meme_list`     表情清单（自适应列数应对上千条）
- `render_top_chart`     调用统计排行
"""

from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from gsuid_core.logger import logger


# ---- Design tokens ----------------------------------------------------------

BG = (15, 18, 22)
SURFACE = (22, 26, 32)
HAIRLINE = (44, 49, 59)
HAIRLINE_SOFT = (33, 37, 45)
TEXT = (236, 231, 221)
MUTED = (123, 128, 144)
DIMMED = (88, 92, 104)
GOLD = (229, 183, 103)
GOLD_DIM = (124, 100, 56)
SAGE = (135, 183, 150)
ROSE = (220, 132, 151)
MAUVE = (167, 138, 182)

# 单一画布宽度。1100px 在主流 IM 客户端缩到 ~360px 时，正文字号仍清晰
WIDTH = 1100
PAD = 64


# ---- 字体加载 ---------------------------------------------------------------

_FONTS_BUNDLED = Path("/usr/share/fonts/memes")

_DISPLAY_CANDIDATES: List[str] = [
    str(_FONTS_BUNDLED / "NotoSerifSC-Bold.otf"),
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-SemiBold.ttc",
    str(_FONTS_BUNDLED / "NotoSansSC-Bold.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

_SERIF_CANDIDATES: List[str] = [
    str(_FONTS_BUNDLED / "NotoSerifSC-Regular.otf"),
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Medium.ttc",
] + _DISPLAY_CANDIDATES

_BODY_CANDIDATES: List[str] = [
    str(_FONTS_BUNDLED / "NotoSansSC-Regular.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

_SANS_BOLD_CANDIDATES: List[str] = [
    str(_FONTS_BUNDLED / "NotoSansSC-Bold.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

_MONO_CANDIDATES: List[str] = [
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Medium.ttf",
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
    "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
] + _BODY_CANDIDATES


def _load_font(candidates: Sequence[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()  # type: ignore[return-value]


def f_display(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(_DISPLAY_CANDIDATES, size)


def f_serif(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(_SERIF_CANDIDATES, size)


def f_body(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(_BODY_CANDIDATES, size)


def f_sans_bold(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(_SANS_BOLD_CANDIDATES, size)


def f_mono(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(_MONO_CANDIDATES, size)


# ---- 通用绘制工具 -----------------------------------------------------------


def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    if not text:
        return 0, 0
    try:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l, b - t
    except AttributeError:
        return draw.textsize(text, font=font)  # type: ignore[attr-defined]


def _wrap(text: str, font, max_w: int, draw: Optional[ImageDraw.ImageDraw] = None) -> List[str]:
    if not text:
        return []
    if draw is None:
        canvas = Image.new("RGB", (4, 4))
        draw = ImageDraw.Draw(canvas)
    out: List[str] = []
    line = ""
    for ch in text:
        candidate = line + ch
        if _measure(draw, candidate, font)[0] > max_w and line:
            out.append(line)
            line = ch
        else:
            line = candidate
    if line:
        out.append(line)
    return out


def _truncate(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if max_w <= 0:
        return ""
    w, _ = _measure(draw, text, font)
    if w <= max_w:
        return text
    ellipsis = "…"
    while text and _measure(draw, text + ellipsis, font)[0] > max_w:
        text = text[:-1]
    return text + ellipsis


def _hairline(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int, color, weight: int = 1) -> None:
    draw.line([(x0, y), (x1, y)], fill=color, width=weight)


def _eyebrow_mark(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    color=GOLD,
    font=None,
) -> int:
    """画一个左上角的小标记：金色方块 + 字符间距拉开的小标。返回总宽度。"""
    if font is None:
        font = f_mono(15)
    sq = 8
    draw.rectangle((x, y + 5, x + sq, y + 5 + sq), fill=color)
    text = "  ".join(label)
    tw, _ = _measure(draw, text, font)
    draw.text((x + sq + 12, y), text, fill=color, font=font)
    return sq + 12 + tw


def _hero(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    *,
    eyebrow: str,
    title: str,
    subtitle: Optional[str] = None,
    width: int,
) -> int:
    """渲染顶部 hero。返回 hero 之后的 y 坐标。"""
    eyebrow_font = f_mono(15)
    title_font = f_display(76)
    subtitle_font = f_body(22)

    cur = y
    _eyebrow_mark(draw, x, cur, eyebrow, color=GOLD, font=eyebrow_font)
    cur += 32

    draw.text((x, cur), title, fill=TEXT, font=title_font)
    _, th = _measure(draw, title, title_font)
    cur += th + 18

    if subtitle:
        # 装饰性短金线 + 副标题
        _hairline(draw, x, cur + 13, x + 56, GOLD, weight=2)
        draw.text((x + 76, cur), subtitle, fill=MUTED, font=subtitle_font)
        _, sh = _measure(draw, subtitle, subtitle_font)
        cur += max(sh, 28)
    cur += 24
    _hairline(draw, x, cur, x + width, HAIRLINE, weight=1)
    cur += 36
    return cur


def _section_intro(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    *,
    index: int,
    name: str,
    accent_dot: Optional[Tuple[int, int, int]] = None,
    count: Optional[int] = None,
    width: int,
) -> int:
    """章节标题：大号编号 + 标题 + 可选状态点 / 计数。"""
    num_font = f_mono(46)
    name_font = f_serif(32)
    count_font = f_mono(20)

    cur = y
    num = f"{index:02d}"
    draw.text((x, cur - 4), num, fill=GOLD, font=num_font)
    nw, nh = _measure(draw, num, num_font)

    name_x = x + nw + 28
    if accent_dot is not None:
        draw.ellipse((name_x, cur + 14, name_x + 12, cur + 26), fill=accent_dot)
        name_x += 22

    draw.text((name_x, cur + 4), name, fill=TEXT, font=name_font)

    if count is not None:
        cnt = f"{count:,}"
        cw, _ = _measure(draw, cnt, count_font)
        draw.text((x + width - cw, cur + 16), cnt, fill=MUTED, font=count_font)

    cur += max(nh, 36) + 8
    _hairline(draw, x, cur, x + width, HAIRLINE_SOFT)
    cur += 24
    return cur


# ---- 命令帮助 ---------------------------------------------------------------


def render_command_help(
    sections: List[Tuple[str, List[Tuple[str, str, str]]]],
    *,
    title: str = "插件帮助",
    subtitle: str = "",
    footer: str = "",
    width: int = WIDTH,
) -> bytes:
    """
    sections: [(分组名, [(命令, 例子, 说明)])]
    """
    cmd_font = f_sans_bold(30)
    eg_font = f_body(23)
    eg_label_font = f_mono(15)  # 仅纯拉丁 "EG"
    desc_font = f_body(22)

    canvas = Image.new("RGB", (4, 4))
    draw0 = ImageDraw.Draw(canvas)

    body_x = PAD
    body_w = width - PAD * 2
    cmd_indent = 20
    inner_w = body_w - cmd_indent * 2
    item_gap = 22
    section_gap = 44

    height = 0
    height += _hero_height_estimate(title, subtitle)
    for _name, items in sections:
        height += _section_intro_height_estimate()
        if not items:
            height += 60 + item_gap
        else:
            for cmd, eg, desc in items:
                height += _help_item_height(
                    inner_w, cmd, eg, desc, cmd_font, eg_font, eg_label_font, desc_font
                ) + item_gap
        height += section_gap
    height += 80  # footer + padding
    height = max(height, 600)

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    # 右上角 .core_plugin / .memes 装饰
    _draw_corner_mark(draw, width, "CORE  ·  PLUGIN  ·  MEMES")

    y = PAD
    y = _hero(draw, body_x, y, eyebrow="CORE PLUGIN MEMES", title=title, subtitle=subtitle, width=body_w)

    for idx, (name, items) in enumerate(sections, start=1):
        y = _section_intro(draw, body_x, y, index=idx, name=name, width=body_w)

        if not items:
            draw.text((body_x + cmd_indent, y), "（无可用命令）", fill=MUTED, font=desc_font)
            y += 60 + item_gap
            y += section_gap
            continue

        for cmd, eg, desc in items:
            block_h = _help_item_height(
                inner_w, cmd, eg, desc, cmd_font, eg_font, eg_label_font, desc_font
            )
            cy = y
            # 命令行
            draw.text((body_x + cmd_indent, cy), cmd, fill=TEXT, font=cmd_font)
            cy += _measure(draw, cmd, cmd_font)[1] + 8
            # 例子
            if eg:
                eg_label = "EG"
                draw.text(
                    (body_x + cmd_indent, cy + 3),
                    eg_label,
                    fill=GOLD_DIM,
                    font=eg_label_font,
                )
                ew, _ = _measure(draw, eg_label, eg_label_font)
                draw.text(
                    (body_x + cmd_indent + ew + 12, cy),
                    eg,
                    fill=GOLD,
                    font=eg_font,
                )
                cy += _measure(draw, eg, eg_font)[1] + 8
            # 描述
            if desc:
                lines = _wrap(desc, desc_font, inner_w - cmd_indent, draw)
                for line in lines:
                    draw.text((body_x + cmd_indent, cy), line, fill=MUTED, font=desc_font)
                    cy += _measure(draw, line, desc_font)[1] + 4
            # 末尾极细分隔线
            sep_y = y + block_h - 2
            _hairline(draw, body_x + cmd_indent, sep_y, body_x + body_w - cmd_indent, HAIRLINE_SOFT)
            y += block_h + item_gap

        y += section_gap

    # 底部
    if footer:
        _hairline(draw, body_x, height - 70, body_x + body_w, HAIRLINE)
        ft = f_body(16)
        draw.text((body_x, height - 70 + 22), footer, fill=DIMMED, font=ft)

    buf = BytesIO()
    img.save(buf, "WEBP", quality=92, method=4)
    return buf.getvalue()


def _help_item_height(
    inner_w: int,
    cmd: str,
    eg: str,
    desc: str,
    cmd_font,
    eg_font,
    eg_label_font,
    desc_font,
) -> int:
    canvas = Image.new("RGB", (4, 4))
    draw = ImageDraw.Draw(canvas)
    h = 0
    h += _measure(draw, cmd, cmd_font)[1] + 8
    if eg:
        h += _measure(draw, eg, eg_font)[1] + 8
    if desc:
        cmd_indent = 20
        for line in _wrap(desc, desc_font, inner_w - cmd_indent, draw):
            h += _measure(draw, line, desc_font)[1] + 4
    h += 8  # 分隔线 padding
    return h


def _hero_height_estimate(title: str, subtitle: str) -> int:
    canvas = Image.new("RGB", (4, 4))
    draw = ImageDraw.Draw(canvas)
    h = PAD  # 顶部 padding
    h += 32  # eyebrow + 间距
    h += _measure(draw, title or "T", f_display(76))[1] + 18
    if subtitle:
        h += max(_measure(draw, subtitle, f_body(22))[1], 28)
    h += 24 + 36  # 分隔线 + 间距
    return h


def _section_intro_height_estimate() -> int:
    canvas = Image.new("RGB", (4, 4))
    draw = ImageDraw.Draw(canvas)
    nh = _measure(draw, "00", f_mono(46))[1]
    return max(nh, 36) + 8 + 24


def _draw_corner_mark(draw: ImageDraw.ImageDraw, canvas_w: int, text: str) -> None:
    font = f_mono(13)
    spaced = "  ".join(text.split())  # 把空格放大；这里 text 本身已带分隔
    tw, th = _measure(draw, spaced, font)
    x = canvas_w - PAD - tw
    y = PAD - th - 8
    if y < 8:
        return
    draw.text((x, y), spaced, fill=DIMMED, font=font)


# ---- 表情清单（按权限分段，自适应列数应对上千条）-----------------------------


def render_meme_list(
    items: List[Tuple[str, str, bool, bool]],
    *,
    title: str = "表情列表",
    subtitle: str = "",
    columns: int = 0,  # 保留兼容；0 表示自适应
    sectioned: bool = True,  # 保留兼容；目前永远分段
    width: int = WIDTH,
) -> bytes:
    """
    items: [(meme_key, label, user_disabled, globally_disabled)]
    """
    available = [it for it in items if not it[2] and not it[3]]
    user_disabled = [it for it in items if it[2] and not it[3]]
    global_disabled = [it for it in items if it[3]]
    sections = [
        ("可用", SAGE, available),
        ("用户禁用", ROSE, user_disabled),
        ("全局禁用", MAUVE, global_disabled),
    ]

    body_x = PAD
    body_w = width - PAD * 2

    n_total = len(items)
    cols = _adaptive_cols(n_total)
    item_gap_x = 14
    cell_w = (body_w - item_gap_x * (cols - 1)) // cols
    row_h = 32

    canvas = Image.new("RGB", (4, 4))
    draw0 = ImageDraw.Draw(canvas)

    height = 0
    height += _hero_height_estimate(title, subtitle)
    for _name, _color, sec_items in sections:
        height += _section_intro_height_estimate()
        rows = max(1, math.ceil(len(sec_items) / cols)) if sec_items else 1
        height += rows * row_h
        height += 44  # 段间距

    height += 80
    height = max(height, 600)

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    _draw_corner_mark(draw, width, "CORE  ·  PLUGIN  ·  MEMES")

    y = PAD
    y = _hero(
        draw, body_x, y,
        eyebrow="MEMES INDEX",
        title=title,
        subtitle=subtitle,
        width=body_w,
    )

    # 顶部右侧的 legend：●可用 ●用户禁用 ●全局禁用
    _draw_legend(
        draw,
        body_x + body_w,
        y - 60,
        right_aligned=True,
    )

    num_font = f_mono(15)
    label_font = f_body(18)

    for idx, (name, color, sec_items) in enumerate(sections, start=1):
        y = _section_intro(
            draw, body_x, y,
            index=idx, name=name, accent_dot=color,
            count=len(sec_items), width=body_w,
        )

        if not sec_items:
            empty_font = f_serif(20)
            draw.text((body_x + 4, y + 6), "（无）", fill=DIMMED, font=empty_font)
            y += 44
            continue

        # 4-digit width 用作所有 number 列对齐
        num_w, _ = _measure(draw, "0000", num_font)
        for i, (key, label, _ud, _gd) in enumerate(sec_items):
            r = i // cols
            c = i % cols
            cx = body_x + c * (cell_w + item_gap_x)
            cy = y + r * row_h

            num_str = f"{i + 1:>4}"
            draw.text((cx, cy + 6), num_str, fill=GOLD, font=num_font)
            label_x = cx + num_w + 12
            label_max = cell_w - num_w - 12
            label_text = _truncate(draw, label, label_font, label_max)
            draw.text((label_x, cy + 4), label_text, fill=TEXT, font=label_font)

            # 行底部超细分隔线（每行均有，做出表格质感）
            _hairline(
                draw,
                cx,
                cy + row_h - 1,
                cx + cell_w,
                HAIRLINE_SOFT,
            )

        rows = math.ceil(len(sec_items) / cols)
        y += rows * row_h + 44

    buf = BytesIO()
    img.save(buf, "WEBP", quality=88, method=4)
    return buf.getvalue()


def _adaptive_cols(n: int) -> int:
    if n <= 60:
        return 3
    if n <= 240:
        return 4
    if n <= 600:
        return 5
    return 6


def _draw_legend(
    draw: ImageDraw.ImageDraw, x_right: int, y: int, *, right_aligned: bool = True
) -> None:
    font = f_body(15)
    items = [(SAGE, "可用"), (ROSE, "用户禁用"), (MAUVE, "全局禁用")]
    parts: List[Tuple[Tuple[int, int, int], str, int]] = []
    total_w = 0
    sep = 18
    dot_to_text = 8
    for color, label in items:
        tw, _ = _measure(draw, label, font)
        parts.append((color, label, tw))
        total_w += 8 + dot_to_text + tw
    total_w += sep * (len(items) - 1)
    cx = x_right - total_w if right_aligned else x_right
    for color, label, tw in parts:
        draw.ellipse((cx, y + 6, cx + 8, y + 14), fill=color)
        draw.text((cx + 8 + dot_to_text, y), label, fill=MUTED, font=font)
        cx += 8 + dot_to_text + tw + sep


# ---- 调用统计排行 -----------------------------------------------------------


def render_top_chart(
    title: str,
    rows: List[Tuple[str, int]],
    *,
    subtitle: str = "",
    bar_color: Tuple[int, int, int] = GOLD,
    max_width: int = WIDTH,
) -> bytes:
    if not rows:
        rows = [("（无数据）", 0)]

    width = max_width
    body_x = PAD
    body_w = width - PAD * 2

    rank_font = f_mono(28)
    label_font = f_serif(22)
    value_font = f_mono(20)

    rank_col = 70   # "01" 位
    label_col = 320  # 标签列宽
    value_col = 100  # 末尾数字列
    bar_col = body_w - rank_col - label_col - value_col - 32

    row_h = 56
    row_gap = 6

    total = sum(v for _, v in rows)

    canvas = Image.new("RGB", (4, 4))
    draw0 = ImageDraw.Draw(canvas)

    height = 0
    height += _hero_height_estimate(title, subtitle or f"共 {total:,} 次")
    height += 24  # hero 后留白
    height += len(rows) * (row_h + row_gap)
    height += 80
    height = max(height, 600)

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    _draw_corner_mark(draw, width, "CORE  ·  PLUGIN  ·  MEMES")

    y = PAD
    y = _hero(
        draw, body_x, y,
        eyebrow="STATISTICS",
        title=title,
        subtitle=(subtitle or f"共 {total:,} 次"),
        width=body_w,
    )

    max_v = max(v for _, v in rows) or 1
    for i, (label, value) in enumerate(rows):
        cy = y + i * (row_h + row_gap)
        # rank
        rank = f"{i + 1:02d}"
        rank_color = GOLD if i < 3 else MUTED
        draw.text((body_x, cy + 14), rank, fill=rank_color, font=rank_font)

        # label
        label_x = body_x + rank_col
        label_max = label_col - 12
        truncated = _truncate(draw, label, label_font, label_max)
        draw.text((label_x, cy + 16), truncated, fill=TEXT, font=label_font)

        # bar
        bar_x = body_x + rank_col + label_col
        bar_y = cy + (row_h - 8) // 2
        bar_h = 8
        # 轨道
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_col, bar_y + bar_h),
            radius=bar_h // 2,
            fill=HAIRLINE_SOFT,
        )
        # 数据条
        if value > 0:
            ratio = value / max_v
            fill_w = max(bar_h, int(bar_col * ratio))
            color = bar_color if i < 3 else SAGE
            draw.rounded_rectangle(
                (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
                radius=bar_h // 2,
                fill=color,
            )

        # value
        val_str = f"{value:,}"
        vw, _ = _measure(draw, val_str, value_font)
        draw.text(
            (body_x + body_w - vw, cy + 18),
            val_str,
            fill=TEXT if i < 3 else MUTED,
            font=value_font,
        )

        # 行底超细线
        _hairline(
            draw, body_x, cy + row_h, body_x + body_w, HAIRLINE_SOFT
        )

    buf = BytesIO()
    img.save(buf, "WEBP", quality=92, method=4)
    return buf.getvalue()
