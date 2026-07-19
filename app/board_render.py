"""Render a member's (or group's) task board to a PNG.

Pure function module: no DB access, no I/O beyond the bundled fonts.
Callers (commands.py, ui.py, scheduler.py) fetch Task rows and pass them in.
"""
import io
import os
from datetime import date

from PIL import Image, ImageDraw, ImageFont

_FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")

# Mint Ledger palette (matches app/static/style.css and the TaskWA flyer)
MINT = (238, 246, 240)
SAGE = (207, 227, 217)
EMERALD = (20, 113, 82)
EMERALD_DARK = (14, 90, 64)
FOREST = (14, 36, 28)
CREAM = (251, 241, 216)
AMBER = (176, 124, 30)
WHITE = (255, 255, 255)
GRAY = (107, 122, 114)
RED = (192, 57, 43)
CARD_BORDER = (216, 230, 222)

W = 1080  # fixed width; height is computed from content

# (status key, column label, header colour)
SECTIONS = [
    ("blocked", "BLOCKED — needs you", RED),
    ("in_progress", "IN PROGRESS", EMERALD),
    ("open", "TO DO", GRAY),
]


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)


def _due_str(t) -> str:
    due = getattr(t, "due_date", None)
    if not due:
        return ""
    today = date.today()
    if due < today:
        return f"overdue {(today - due).days}d"
    if due == today:
        return "due today"
    return f"due {due:%a %d %b}"


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return draw.textlength(text, font=font)


def render_member_board(member_name: str, header_sub: str,
                         open_tasks: list, done_recent: list | None = None,
                         dev_banner: bool = True) -> bytes:
    """Render one member's board.

    open_tasks: Task rows with status in (open, in_progress, blocked),
        already sorted (engine.sort_tasks order is fine).
    done_recent: optional list of recently-completed Task rows.
    Returns raw PNG bytes.
    """
    done_recent = done_recent or []

    f_title = _font("DejaVuSans-Bold.ttf", 34)
    f_sub = _font("DejaVuSans.ttf", 19)
    f_header = _font("DejaVuSans-Bold.ttf", 24)
    f_card_title = _font("DejaVuSans-Bold.ttf", 26)
    f_meta = _font("DejaVuSans.ttf", 19)
    f_small = _font("DejaVuSans.ttf", 18)
    f_mono = _font("DejaVuSansMono.ttf", 24)
    f_banner = _font("DejaVuSans-Bold.ttf", 20)

    buckets = {key: [t for t in open_tasks if t.status == key]
               for key, _, _ in SECTIONS}
    sections = [(key, label, color, buckets[key])
                for key, label, color in SECTIONS if buckets[key]]
    if done_recent:
        sections.append(("done", "DONE LAST WEEK", EMERALD_DARK, done_recent))

    banner_h = 44 if dev_banner else 0
    header_h = 120
    y = header_h + banner_h + 30
    for _, _, _, rows in sections:
        y += 70  # section header + gap
        for t in rows:
            is_blocked = t.status == "blocked" and getattr(t, "blocker_reason", "")
            y += 116 if is_blocked else 96
        y += 18
    H = max(700, y + 130)  # + footer

    img = Image.new("RGB", (W, H), MINT)
    d = ImageDraw.Draw(img)

    # dev-in-progress banner
    if dev_banner:
        d.rectangle([0, 0, W, banner_h], fill=AMBER)
        msg = "TaskWA Kanban — v1.7, in development"
        tw = _text_w(d, msg, f_banner)
        d.text(((W - tw) / 2, (banner_h - 20) / 2), msg, font=f_banner, fill=WHITE)

    # header
    top = banner_h
    d.rectangle([0, top, W, top + header_h], fill=EMERALD_DARK)
    d.text((56, top + 28), f"TaskWA · Board — {member_name}",
           font=f_title, fill=WHITE)
    d.text((56, top + 78), header_sub, font=f_sub, fill=SAGE)

    y = top + header_h + 30
    for key, label, color, rows in sections:
        d.rounded_rectangle([56, y, 1024, y + 54], 12, fill=color)
        d.text((84, y + 14), label, font=f_header, fill=WHITE)
        count = str(len(rows))
        cw = _text_w(d, count, f_header)
        d.text((1024 - 28 - cw, y + 14), count, font=f_header, fill=WHITE)

        yy = y + 70
        for t in rows:
            is_done = key == "done"
            is_blocked = t.status == "blocked" and getattr(t, "blocker_reason", "")
            h = 104 if is_blocked else 84
            d.rounded_rectangle([56, yy, 1024, yy + h], 12,
                                 fill=WHITE, outline=CARD_BORDER)
            # serial chip
            d.rounded_rectangle([76, yy + 22, 140, yy + 62], 10, fill=MINT)
            serial = str(t.id)
            sw = _text_w(d, serial, f_mono)
            d.text((108 - sw / 2, yy + 28), serial, font=f_mono, fill=EMERALD_DARK)

            title_color = GRAY if is_done else FOREST
            title = t.title if len(t.title) <= 46 else t.title[:45] + "…"
            d.text((160, yy + 14), title, font=f_card_title, fill=title_color)

            if is_done:
                meta = "done"
            else:
                meta = getattr(t, "priority", "medium")
                due = _due_str(t)
                if due:
                    meta += f" · {due}"
            d.text((160, yy + 50), meta, font=f_meta, fill=GRAY)

            if is_blocked:
                bd = getattr(t, "blocked_days", 0)
                reason = t.blocker_reason[:60]
                d.text((160, yy + 74), f"Blocked {bd}d: {reason}",
                       font=f_small, fill=RED)
            yy += h + 12
        y = yy + 18

    # footer — reply syntax uses the GLOBAL serial
    d.rectangle([0, H - 120, W, H], fill=EMERALD_DARK)
    example_id = open_tasks[0].id if open_tasks else 1
    d.text((56, H - 88),
           f"Reply:  {example_id} done  ·  {example_id} in progress  ·  "
           f"{example_id} block <reason>",
           font=f_mono, fill=WHITE)
    d.text((56, H - 50), "Serial numbers work in your daily digest too",
           font=f_small, fill=SAGE)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def render_group_board(group_name: str, header_sub: str,
                        open_tasks: list, dev_banner: bool = True) -> bytes:
    """Render a group board. Same layout as a member board, but each card
    shows the assignee's name (open_tasks rows must have .assignee.name)."""
    # Reuse render_member_board's layout by temporarily tagging titles with
    # the assignee name, so callers don't need a second code path to keep
    # in sync. Kept as a thin wrapper deliberately — one rendering engine.
    tagged = []
    for t in open_tasks:
        assignee = getattr(t, "assignee", None)
        name = getattr(assignee, "name", "?") if assignee else "?"
        clone = _TaskView(t, f"{t.title} — {name}")
        tagged.append(clone)
    return render_member_board(group_name, header_sub, tagged,
                                dev_banner=dev_banner)


class _TaskView:
    """Read-only view over a Task that overrides .title, used only to
    annotate group-board cards with the assignee's name without mutating
    the real ORM row."""

    def __init__(self, task, title):
        self._task = task
        self.title = title

    def __getattr__(self, item):
        return getattr(self._task, item)
