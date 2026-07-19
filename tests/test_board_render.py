"""Tests for app/board_render.py — pure rendering, no DB, no app wiring."""
from datetime import date, timedelta

from PIL import Image

from app.board_render import render_member_board, render_group_board


class FakeTask:
    """Duck-typed stand-in for a models.Task row — mirrors the attributes
    board_render.py actually reads, nothing more."""

    def __init__(self, id, title, status="open", priority="medium",
                 due_date=None, blocker_reason="", blocked_days=0,
                 assignee_name=None):
        self.id = id
        self.title = title
        self.status = status
        self.priority = priority
        self.due_date = due_date
        self.blocker_reason = blocker_reason
        self.blocked_days = blocked_days
        self.assignee = FakeAssignee(assignee_name) if assignee_name else None


class FakeAssignee:
    def __init__(self, name):
        self.name = name


def _png_size(png_bytes):
    img = Image.open(__import__("io").BytesIO(png_bytes))
    return img.size


def test_renders_nonempty_png_for_empty_board():
    png = render_member_board("Ravi", "0 open · 0 blocked", [], [])
    assert isinstance(png, bytes)
    assert len(png) > 0
    w, h = _png_size(png)
    assert w == 1080
    assert h > 0


def test_renders_open_and_blocked_tasks():
    tasks = [
        FakeTask(1, "Fix invoice bug", status="open", priority="high"),
        FakeTask(2, "Ship v1.7", status="in_progress", priority="medium",
                 due_date=date.today() + timedelta(days=2)),
        FakeTask(3, "Renew GO", status="blocked", priority="high",
                 blocker_reason="waiting on Karnataka DISCOM approval",
                 blocked_days=5),
    ]
    png = render_member_board("Ravi", "3 open · 1 blocked", tasks, [])
    assert len(png) > 0
    w, h = _png_size(png)
    assert w == 1080


def test_height_grows_with_more_tasks():
    few = [FakeTask(i, f"Task {i}") for i in range(2)]
    many = [FakeTask(i, f"Task {i}") for i in range(20)]
    png_few = render_member_board("Ravi", "sub", few, [])
    png_many = render_member_board("Ravi", "sub", many, [])
    _, h_few = _png_size(png_few)
    _, h_many = _png_size(png_many)
    assert h_many > h_few


def test_done_recent_appended_as_section():
    # Enough open tasks to clear the 700px minimum-height floor, so the
    # added "done" section actually moves the needle in this comparison.
    open_tasks = [FakeTask(i, f"Open {i}", status="open") for i in range(8)]
    done = [FakeTask(100, "Closed one", status="done")]
    png_without = render_member_board("Ravi", "sub", open_tasks, [])
    png_with = render_member_board("Ravi", "sub", open_tasks, done)
    _, h_without = _png_size(png_without)
    _, h_with = _png_size(png_with)
    assert h_with > h_without


def test_dev_banner_toggle_changes_height():
    # Same floor issue as above: enough tasks to clear 700px so the 44px
    # banner difference is actually visible in the output height.
    tasks = [FakeTask(i, f"Task {i}") for i in range(8)]
    png_banner = render_member_board("Ravi", "sub", tasks, [], dev_banner=True)
    png_no_banner = render_member_board("Ravi", "sub", tasks, [], dev_banner=False)
    _, h_banner = _png_size(png_banner)
    _, h_no_banner = _png_size(png_no_banner)
    assert h_banner > h_no_banner


def test_long_title_is_truncated_not_erroring():
    long_title = "A" * 200
    tasks = [FakeTask(1, long_title)]
    png = render_member_board("Ravi", "sub", tasks, [])
    assert len(png) > 0


def test_group_board_tags_assignee_name():
    tasks = [FakeTask(1, "Fix invoice bug", assignee_name="Priya")]
    png = render_group_board("Site B", "sub", tasks)
    assert len(png) > 0
    w, h = _png_size(png)
    assert w == 1080


def test_empty_group_board_renders():
    png = render_group_board("Site B", "0 open", [])
    assert len(png) > 0
