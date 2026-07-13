"""Admin dashboard: login, setup wizard, tasks, members, groups, settings, health."""
import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import (HTMLResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.templating import Jinja2Templates
import os

from . import security, waha
from .db import get_setting, session_scope, set_setting
from .engine import (bulk_add_members, change_status, create_task,
                     sort_tasks)
from .models import (Broadcast, Group, Member, MessageLog,
                     StatusEvent, Task, PRIORITIES, STATUSES)

router = APIRouter()
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates"))


def _localtime(value, fmt="%d %b %H:%M"):
    """Render a stored UTC timestamp (datetime or ISO string) in the
    installation's configured timezone."""
    from datetime import datetime as _dt, timezone as _tz
    from zoneinfo import ZoneInfo
    if not value:
        return "never"
    if isinstance(value, str):
        try:
            value = _dt.fromisoformat(value)
        except ValueError:
            return value
    with session_scope() as s:
        tzname = get_setting(s, "timezone") or "UTC"
    try:
        local = value.replace(tzinfo=_tz.utc).astimezone(ZoneInfo(tzname))
    except Exception:
        return value.strftime(fmt)
    return local.strftime(fmt)


templates.env.filters["localtime"] = _localtime


def _fromjson(value):
    import json as _j
    try:
        return _j.loads(value or "[]")
    except ValueError:
        return []


templates.env.filters["fromjson"] = _fromjson


def _authed(request: Request) -> bool:
    return security.check_cookie(request.cookies.get(security.COOKIE))


def _guard(request: Request):
    """Returns a redirect response if not authed / not set up, else None."""
    with session_scope() as s:
        if not get_setting(s, "setup_complete"):
            return RedirectResponse("/setup", status_code=303)
    if not _authed(request):
        return RedirectResponse("/login", status_code=303)
    return None


def _ctx(request: Request, s, **extra):
    ctx = {"request": request,
           "gateway_status": get_setting(s, "gateway_status"),
           "dry_run": get_setting(s, "dry_run")}
    ctx.update(extra)
    return ctx


# ---------------- auth ----------------
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html",
                                      {"request": request, "error": error})


@router.post("/login")
def login(request: Request, password: str = Form(...)):
    if security.verify_password(password):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(security.COOKIE, security.make_cookie(),
                        httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login?error=Wrong+password", status_code=303)


@router.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(security.COOKIE)
    return resp


@router.post("/forgot")
def forgot():
    sent = security.send_reset_code()
    msg = ("Code+sent+to+the+admin+WhatsApp" if sent
           else "Could+not+send+-+no+admin+registered+or+gateway+down.+Use+the+CLI+reset.")
    return RedirectResponse(f"/reset?info={msg}", status_code=303)


@router.get("/reset", response_class=HTMLResponse)
def reset_page(request: Request, info: str = "", error: str = ""):
    return templates.TemplateResponse(request,
        "reset.html", {"request": request, "info": info, "error": error})


@router.post("/reset")
def reset(code: str = Form(...), password: str = Form(...)):
    if len(password) < 8:
        return RedirectResponse("/reset?error=Password+must+be+8%2B+characters",
                                status_code=303)
    if security.verify_reset_code(code):
        security.set_password(password)
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/reset?error=Invalid+or+expired+code", status_code=303)


# ---------------- setup wizard ----------------
@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    with session_scope() as s:
        if get_setting(s, "setup_complete"):
            return RedirectResponse("/", status_code=303)
        has_pw = bool(get_setting(s, "admin_password_hash"))
        members = s.query(Member).all()
        tz = get_setting(s, "timezone")
        times = ", ".join(get_setting(s, "send_times"))
        return templates.TemplateResponse(request, "setup.html", {
            "request": request, "has_pw": has_pw, "members": members,
            "timezone": tz, "send_times": times,
            "gateway_status": waha.session_status()})


@router.post("/setup/password")
def setup_password(password: str = Form(...)):
    if len(password) >= 8:
        security.set_password(password)
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/start-session")
def setup_start_session():
    waha.start_session()
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/basics")
def setup_basics(timezone: str = Form(...), send_times: str = Form(...)):
    with session_scope() as s:
        set_setting(s, "timezone", timezone.strip())
        set_setting(s, "send_times",
                    [t.strip() for t in send_times.split(",") if t.strip()])
    from .scheduler import reload_digest_jobs
    reload_digest_jobs()
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/member")
def setup_member(name: str = Form(...), phone: str = Form(...),
                 role: str = Form("member")):
    with session_scope() as s:
        s.add(Member(name=name.strip(),
                     phone="".join(c for c in phone if c.isdigit()),
                     role=role if role in ("admin", "member") else "member"))
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/test")
def setup_test():
    with session_scope() as s:
        admin = (s.query(Member).filter(Member.role == "admin",
                                        Member.active.is_(True)).first())
    if admin:
        waha.send_text(waha.chat_id_for_phone(admin.phone),
                       "Test message from TaskWA. Setup looks good!")
    return RedirectResponse("/setup", status_code=303)


@router.post("/setup/finish")
def setup_finish():
    with session_scope() as s:
        if get_setting(s, "admin_password_hash") and \
           s.query(Member).filter(Member.role == "admin").count() > 0:
            set_setting(s, "setup_complete", True)
    return RedirectResponse("/login", status_code=303)


# ---------------- tasks ----------------
@router.get("/", response_class=HTMLResponse)
def tasks_page(request: Request, status: str = "open", assignee: int = 0,
               err: str = ""):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        q = s.query(Task)
        if status == "open":
            q = q.filter(Task.status.in_(("open", "in_progress", "blocked")))
        elif status in STATUSES:
            q = q.filter(Task.status == status)
        if assignee:
            q = q.filter(Task.assignee_id == assignee)
        tasks = sort_tasks(q.all()) if status == "open" else \
            q.order_by(Task.updated_at.desc()).limit(200).all()
        members = s.query(Member).filter(Member.active.is_(True)).all()
        groups = s.query(Group).filter(Group.active.is_(True)).all()
        return templates.TemplateResponse(request, "tasks.html", _ctx(
            request, s, tasks=tasks, members=members, groups=groups,
            f_status=status, f_assignee=assignee, today=date.today(),
            priorities=PRIORITIES, err=err[:200]))


@router.post("/tasks/create")
def task_create(request: Request, title: str = Form(...),
                assignee_id: int = Form(...), priority: str = Form("medium"),
                due_date: str = Form(""), description: str = Form(""),
                post_to_group_id: str = Form("")):
    if (r := _guard(request)):
        return r
    notify = None
    with session_scope() as s:
        assignee = s.get(Member, assignee_id)
        admin = s.query(Member).filter(Member.role == "admin").first()
        t = create_task(s, title=title, assignee=assignee, creator=admin,
                        description=description, priority=priority,
                        due_date=date.fromisoformat(due_date) if due_date else None,
                        post_to_group_id=int(post_to_group_id) if post_to_group_id else None,
                        channel="dashboard")
        from .commands import notify_assignee
        notify = notify_assignee(s, t, admin)
    if notify:
        waha.send_text(*notify)
    return RedirectResponse("/", status_code=303)


@router.post("/tasks/{task_id}/status")
def task_status(request: Request, task_id: int, new_status: str = Form(...),
                note: str = Form("")):
    if (r := _guard(request)):
        return r
    from urllib.parse import quote
    notify = None
    with session_scope() as s:
        t = s.get(Task, task_id)
        if t is None:
            return RedirectResponse("/?err=" + quote(f"No task #{task_id}."),
                                    status_code=303)
        try:
            change_status(s, t, None, new_status, note=note,
                          channel="dashboard")
        except Exception as e:
            # surface the reason instead of silently doing nothing
            return RedirectResponse("/?err=" + quote(str(e)), status_code=303)
        # parity with WhatsApp: the assignee hears about a done/cancel
        # done on their behalf (one message, group or DM - never both)
        if (new_status in ("done", "cancelled") and t.assignee
                and t.assignee.role != "admin"):   # admins did it themselves
            from .commands import _task_channel
            verb = "closed" if new_status == "done" else "cancelled"
            why = f" ({note.strip()})" if note.strip() else ""
            notify = (_task_channel(s, t),
                      f"Admin {verb} task #{t.id}: {t.title}{why} - "
                      f"it's off your list, {t.assignee.name}.")
    if notify:
        waha.send_text(*notify)
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


@router.post("/tasks/{task_id}/edit")
def task_edit(request: Request, task_id: int, title: str = Form(...),
              assignee_id: int = Form(...), priority: str = Form("medium"),
              due_date: str = Form(""), description: str = Form(""),
              post_to_group_id: str = Form("")):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        t = s.get(Task, task_id)
        if t:
            t.title = title.strip()[:200]
            t.assignee_id = assignee_id
            t.priority = priority if priority in PRIORITIES else "medium"
            t.due_date = date.fromisoformat(due_date) if due_date else None
            t.description = description
            t.post_to_group_id = int(post_to_group_id) if post_to_group_id else None
            s.add(StatusEvent(task_id=t.id, from_status=t.status,
                              to_status=t.status, note="edited",
                              channel="dashboard"))
    return RedirectResponse("/", status_code=303)


# ---------------- members & groups ----------------
@router.get("/members", response_class=HTMLResponse)
def members_page(request: Request, imported: int = -1, skipped: int = 0):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        members = s.query(Member).order_by(Member.active.desc(), Member.name).all()
        groups = s.query(Group).filter(Group.active.is_(True)).all()
        return templates.TemplateResponse(request, "members.html", _ctx(
            request, s, members=members, groups=groups,
            imported=imported, skipped=skipped))


@router.get("/members/import", response_class=HTMLResponse)
def members_import(request: Request, group_id: int = 0):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        groups = s.query(Group).filter(Group.active.is_(True)).all()
        group = s.get(Group, group_id) if group_id else None
        existing = {m.phone for m in s.query(Member).all()}
    parts, me_phone = [], ""
    if group:
        me = waha.me_chat_id() or ""
        me_phone = me.split("@")[0]
        parts = waha.group_participants(group.chat_id)
    with session_scope() as s:
        return templates.TemplateResponse(request, "members_import.html", _ctx(
            request, s, groups=groups, group=group, parts=parts,
            existing=existing, me_phone=me_phone))


@router.post("/members/import")
async def members_import_post(request: Request):
    if (r := _guard(request)):
        return r
    form = await request.form()
    rows = []
    for key in form.keys():
        if key.startswith("sel_"):
            i = key[4:]
            rows.append({"name": form.get(f"name_{i}", ""),
                         "phone": form.get(f"phone_{i}", ""),
                         "role": form.get(f"role_{i}", "member")})
    with session_scope() as s:
        added, skipped = bulk_add_members(s, rows)
    return RedirectResponse(f"/members?imported={added}&skipped={skipped}",
                            status_code=303)


@router.post("/members/add")
def member_add(request: Request, name: str = Form(...), phone: str = Form(...),
               role: str = Form("member")):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        s.add(Member(name=name.strip(),
                     phone="".join(c for c in phone if c.isdigit()),
                     role=role if role in ("admin", "member") else "member"))
    return RedirectResponse("/members", status_code=303)


@router.post("/members/{member_id}/toggle")
def member_toggle(request: Request, member_id: int):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        m = s.get(Member, member_id)
        if m:
            m.active = not m.active
    return RedirectResponse("/members", status_code=303)


@router.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request, detect: int = 0):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        groups = s.query(Group).all()
        detected = []
        detect_failed = False
        if detect:
            found = waha.list_groups()
            known = {g.chat_id for g in groups}
            detected = [d for d in found if d["chat_id"] not in known]
            detect_failed = not found
        return templates.TemplateResponse(request, "groups.html", _ctx(
            request, s, groups=groups, detected=detected,
            detect_ran=bool(detect), detect_failed=detect_failed))


@router.post("/groups/add")
def group_add(request: Request, name: str = Form(...), chat_id: str = Form(...)):
    if (r := _guard(request)):
        return r
    cid = chat_id.strip()
    if not cid.endswith("@g.us"):
        cid += "@g.us"
    with session_scope() as s:
        s.add(Group(name=name.strip(), chat_id=cid))
    return RedirectResponse("/groups", status_code=303)


@router.post("/groups/{group_id}/toggle")
def group_toggle(request: Request, group_id: int):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        g = s.get(Group, group_id)
        if g:
            g.active = not g.active
    return RedirectResponse("/groups", status_code=303)


# ---------------- broadcasts ----------------
import json as _json


def _parse_broadcast_form(form):
    from .broadcasts import valid_tz
    days = [int(d) for d in form.getlist("days")] if hasattr(form, "getlist") else []
    tz = str(form.get("tz", "")).strip()
    return dict(
        name=str(form.get("name", "")).strip()[:80] or "Untitled",
        message=str(form.get("message", "")).strip(),
        member_ids=_json.dumps([int(x) for x in form.getlist("member_ids")]),
        group_ids=_json.dumps([int(x) for x in form.getlist("group_ids")]),
        days=_json.dumps(days),
        send_time=str(form.get("send_time", "")).strip(),
        tz=tz if valid_tz(tz) else "",   # "" is replaced with the setting on save
        active=form.get("active") == "on",
    )


def _bcast_ctx(request, s, b=None):
    import zoneinfo
    from .broadcasts import COMMON_TZS, DAY_NAMES
    tz_default = get_setting(s, "timezone") or "UTC"
    other_tzs = sorted(zoneinfo.available_timezones() - set(COMMON_TZS))
    return _ctx(request, s,
                broadcasts=s.query(Broadcast).order_by(Broadcast.name).all(),
                members=s.query(Member).filter(Member.active.is_(True)).all(),
                groups_all=s.query(Group).filter(Group.active.is_(True)).all(),
                day_names=DAY_NAMES, b=b,
                tz_default=tz_default, common_tzs=COMMON_TZS,
                other_tzs=other_tzs,
                b_members=_json.loads(b.member_ids) if b else [],
                b_groups=_json.loads(b.group_ids) if b else [],
                b_days=_json.loads(b.days) if b else [])


@router.get("/broadcasts", response_class=HTMLResponse)
def broadcasts_page(request: Request, edit: int = 0, sent: int = 0):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        b = s.get(Broadcast, edit) if edit else None
        ctx = _bcast_ctx(request, s, b)
        ctx["sent"] = sent
        return templates.TemplateResponse(request, "broadcasts.html", ctx)


@router.post("/broadcasts/save")
async def broadcast_save(request: Request):
    if (r := _guard(request)):
        return r
    form = await request.form()
    bid = int(form.get("id") or 0)
    data = _parse_broadcast_form(form)
    with session_scope() as s:
        if not data["tz"]:   # nothing/invalid submitted -> pin today's setting
            data["tz"] = get_setting(s, "timezone") or "UTC"
        b = s.get(Broadcast, bid) if bid else None
        if b is None:
            b = Broadcast()
            s.add(b)
        for k, v in data.items():
            setattr(b, k, v)
    from .scheduler import reload_broadcast_jobs
    reload_broadcast_jobs()
    return RedirectResponse("/broadcasts", status_code=303)


@router.post("/broadcasts/{bid}/delete")
def broadcast_delete(request: Request, bid: int):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        b = s.get(Broadcast, bid)
        if b:
            s.delete(b)
    from .scheduler import reload_broadcast_jobs
    reload_broadcast_jobs()
    return RedirectResponse("/broadcasts", status_code=303)


@router.post("/broadcasts/{bid}/send-now")
def broadcast_send_now(request: Request, bid: int):
    if (r := _guard(request)):
        return r
    from .scheduler import run_broadcast_soon
    run_broadcast_soon(bid)
    return RedirectResponse("/broadcasts?sent=1", status_code=303)


# ---------------- settings, health, export ----------------
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        return templates.TemplateResponse(request, "settings.html", _ctx(
            request, s,
            timezone=get_setting(s, "timezone"),
            send_times=", ".join(get_setting(s, "send_times")),
            ack_mode=get_setting(s, "ack_mode"),
            personal_mode=get_setting(s, "personal_mode"),
            hourly_cap=get_setting(s, "hourly_cap"),
            purge_after_days=get_setting(s, "purge_after_days")))


@router.post("/settings")
def settings_save(request: Request, timezone: str = Form(...),
                  send_times: str = Form(...), ack_mode: str = Form(...),
                  hourly_cap: int = Form(60), purge_after_days: int = Form(30),
                  dry_run: str = Form(""), personal_mode: str = Form("")):
    if (r := _guard(request)):
        return r
    with session_scope() as s:
        set_setting(s, "timezone", timezone.strip())
        set_setting(s, "send_times",
                    [t.strip() for t in send_times.split(",") if t.strip()])
        set_setting(s, "ack_mode",
                    ack_mode if ack_mode in ("none", "reaction", "reply") else "reaction")
        set_setting(s, "hourly_cap", max(1, hourly_cap))
        set_setting(s, "purge_after_days", max(1, purge_after_days))
        set_setting(s, "dry_run", dry_run == "on")
        set_setting(s, "personal_mode", personal_mode == "on")
    from .scheduler import reload_broadcast_jobs, reload_digest_jobs
    reload_digest_jobs()
    reload_broadcast_jobs()   # legacy/fallback rows follow the new timezone
    return RedirectResponse("/settings", status_code=303)


@router.get("/health", response_class=HTMLResponse)
def health_page(request: Request):
    if (r := _guard(request)):
        return r
    status = waha.session_status()
    with session_scope() as s:
        log_rows = (s.query(MessageLog)
                     .order_by(MessageLog.created_at.desc()).limit(30).all())
        return templates.TemplateResponse(request, "health.html", _ctx(
            request, s, status=status,
            last_send=get_setting(s, "last_send"),
            last_backup=get_setting(s, "last_backup"),
            tzname=get_setting(s, "timezone") or "UTC",
            log_rows=log_rows))


@router.post("/health/start-session")
def health_start(request: Request):
    if (r := _guard(request)):
        return r
    waha.start_session()
    return RedirectResponse("/health", status_code=303)


@router.post("/health/send-digests-now")
def health_digests(request: Request):
    if (r := _guard(request)):
        return r
    from .digest import send_daily_digests
    send_daily_digests()
    return RedirectResponse("/health", status_code=303)


@router.get("/qr.png")
def qr_image(request: Request):
    with session_scope() as s:
        setup_done = get_setting(s, "setup_complete")
    if setup_done and not _authed(request):
        return Response(status_code=403)
    png = waha.qr_png()
    if png:
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "no-store"})
    return Response(status_code=404)


@router.get("/export/{what}.csv")
def export_csv(request: Request, what: str):
    if (r := _guard(request)):
        return r
    buf = io.StringIO()
    w = csv.writer(buf)
    with session_scope() as s:
        if what == "tasks":
            w.writerow(["id", "title", "assignee", "priority", "status",
                        "due_date", "blocker_reason", "created_at",
                        "completed_at"])
            for t in s.query(Task).all():
                w.writerow([t.id, t.title, t.assignee.name, t.priority,
                            t.status, t.due_date, t.blocker_reason,
                            t.created_at, t.completed_at])
        elif what == "audit":
            w.writerow(["task_id", "actor", "from", "to", "note", "channel",
                        "raw_text", "at"])
            for e in s.query(StatusEvent).order_by(StatusEvent.created_at).all():
                w.writerow([e.task_id, e.actor.name if e.actor else "",
                            e.from_status, e.to_status, e.note, e.channel,
                            e.raw_text, e.created_at])
        else:
            return Response(status_code=404)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      f"attachment; filename={what}.csv"})
