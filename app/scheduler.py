"""APScheduler jobs: daily digests, gateway health, nightly backup, purge."""
import csv
import logging
import os
import shutil
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import env
from .db import DB_PATH, get_setting, session_scope, set_setting
from .digest import send_daily_digests
from .models import MessageLog, ProcessedMessage, StatusEvent, Task
from .waha import session_status

log = logging.getLogger("scheduler")
scheduler = BackgroundScheduler()

_DIGEST_JOB_PREFIX = "digest-"
_BCAST_JOB_PREFIX = "bcast-"
_BOARD_JOB_ID = "weekly-board"
# APScheduler numbers weekdays with its own convention; map 0=Mon..6=Sun to
# names explicitly so the stored setting means exactly what the label says.
_DOW_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def jitter_seconds() -> int:
    """How far either side of the scheduled minute a run may drift. APScheduler
    applies this as +/- jitter, so 6 min means the 08:00 digest starts between
    07:54 and 08:06 - never the same second every day."""
    with session_scope() as s:
        return max(0, int(get_setting(s, "jitter_minutes") or 0)) * 60


def reload_digest_jobs():
    """(Re)create one cron job per configured send time."""
    for job in scheduler.get_jobs():
        if job.id.startswith(_DIGEST_JOB_PREFIX):
            scheduler.remove_job(job.id)
    with session_scope() as s:
        tz = ZoneInfo(get_setting(s, "timezone") or "UTC")
        times = get_setting(s, "send_times") or ["08:00"]
    jit = jitter_seconds()
    for t in times:
        try:
            hh, mm = t.strip().split(":")
            scheduler.add_job(send_daily_digests, CronTrigger(
                hour=int(hh), minute=int(mm), timezone=tz, jitter=jit or None),
                id=f"{_DIGEST_JOB_PREFIX}{t}", replace_existing=True,
                misfire_grace_time=6 * 3600, coalesce=True)
        except Exception as e:
            log.error("bad send time %r: %s", t, e)
    log.info("digest jobs: %s", [j.id for j in scheduler.get_jobs()
                                 if j.id.startswith(_DIGEST_JOB_PREFIX)])


# ---------------- health & gateway auto-recovery ----------------
_last_alerted_status = {"value": None}

# A FAILED/STOPPED session whose WhatsApp auth is still valid recovers with a
# plain restart (no QR). We try that on a widening backoff, then give up and
# ask a human - because relentlessly restarting/re-pairing a personal number
# is itself a ban signal. Index = attempts already made; value = minutes we
# must have waited since the last restart before trying again. attempt 0 fires
# immediately; after AUTO_RESTART_MAX tries we stop and escalate.
AUTO_RESTART_BACKOFF_MIN = [0, 5, 15, 30]
AUTO_RESTART_MAX = len(AUTO_RESTART_BACKOFF_MIN)

# Statuses a plain restart can fix (auth preserved). Everything else either
# needs a human (SCAN_QR_CODE / PASSKEY_* = WhatsApp de-authorised the device)
# or is out of our hands (UNREACHABLE = the WAHA container itself is down; the
# docker restart policy owns that, not us).
_RESTARTABLE = {"FAILED", "STOPPED", "NOT_STARTED"}
_NEEDS_REPAIR = {"SCAN_QR_CODE", "PASSKEY_REQUIRED",
                 "PASSKEY_CONFIRMATION_REQUIRED"}


def plan_gateway_action(status: str, attempts: int, mins_since_last,
                        enabled: bool) -> str:
    """Pure decision for the health state machine (no side effects, testable).

    Returns one of:
      'noop'     - WORKING; nothing to do.
      'restart'  - issue an auto-restart now (caller then increments attempts).
      'wait'     - restartable, but the backoff window hasn't elapsed; hold.
      'escalate' - stop trying and alert a human (auto-restart disabled,
                   budget exhausted, a QR re-pair is needed, or the container
                   is unreachable).

    Never returns 'restart' for a status outside _RESTARTABLE - a QR re-scan
    or a dead container is not something restarting can fix, and looping it
    would only add ban risk."""
    if status == "WORKING":
        return "noop"
    if status in _RESTARTABLE:
        if not enabled or attempts >= AUTO_RESTART_MAX:
            return "escalate"
        if attempts <= 0:
            return "restart"
        need = AUTO_RESTART_BACKOFF_MIN[attempts]
        if mins_since_last is None or mins_since_last >= need:
            return "restart"
        return "wait"
    return "escalate"


def _minutes_since(iso: str):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return (datetime.utcnow() - dt).total_seconds() / 60.0


def _alert_once(status: str, subject: str, body: str):
    """Email a human at most once per distinct status, so a session that sits
    FAILED for hours doesn't email every 5 minutes."""
    if _last_alerted_status["value"] == status:
        return
    _last_alerted_status["value"] = status
    _email_alert(subject, body)


def check_gateway_health():
    # Read the PREVIOUS status BEFORE session_status() refreshes the cache -
    # session_status() writes gateway_status itself, so reading it afterwards
    # would just hand us back the new value and the transition (was-WORKING ->
    # now-FAILED) would never be detectable.
    with session_scope() as s:
        prev = get_setting(s, "gateway_status")
        enabled = bool(get_setting(s, "auto_restart_enabled"))
        attempts = int(get_setting(s, "gateway_restart_attempts") or 0)
        last_at = get_setting(s, "gateway_restart_at") or ""
    status = session_status()   # refreshes cached gateway_status / _at
    action = plan_gateway_action(status, attempts, _minutes_since(last_at),
                                 enabled)

    if env.healthchecks_url and status == "WORKING":
        try:
            httpx.get(env.healthchecks_url, timeout=10)
        except Exception:
            pass

    if status == "WORKING":
        _last_alerted_status["value"] = None
        if attempts:
            with session_scope() as s:      # recovered - clear the budget
                set_setting(s, "gateway_restart_attempts", 0)
                set_setting(s, "gateway_restart_at", "")
        if prev != "WORKING":
            log.info("gateway recovered to WORKING (was %s)", prev)
            # populate WAHA's lid->phone map so group replies resolve
            try:
                from .waha import list_groups
                list_groups()
            except Exception as e:
                log.warning("lid warmup failed: %s", e)
        return

    if action == "restart":
        from .waha import restart_session
        n = attempts + 1
        log.warning("gateway %s - auto-restart attempt %d/%d",
                    status, n, AUTO_RESTART_MAX)
        try:
            restart_session()
        except Exception as e:
            log.error("auto-restart call failed: %s", e)
        with session_scope() as s:
            set_setting(s, "gateway_restart_attempts", n)
            set_setting(s, "gateway_restart_at",
                        datetime.utcnow().isoformat(timespec="seconds"))
        if prev == "WORKING":   # first drop - tell the human it's being handled
            _alert_once(status, f"WhatsApp gateway session is {status}",
                        f"The gateway went {status}; auto-restart attempt "
                        f"{n}/{AUTO_RESTART_MAX} has been issued. You'll get a "
                        "re-pair alert only if the restarts don't recover it.")
        return

    if action == "wait":
        return   # backoff window not elapsed; hold without spamming

    # action == "escalate"
    if status in _NEEDS_REPAIR:
        _alert_once(status, "WhatsApp gateway needs re-pairing",
                    "WhatsApp logged the device out - a restart can't fix this.\n"
                    "Open the dashboard Health page and use 'Re-pair (new QR)', "
                    "then scan with the number's phone.")
    elif status == "UNREACHABLE":
        _alert_once(status, "WhatsApp gateway UNREACHABLE",
                    "The WAHA container isn't answering. Docker should restart "
                    "it (restart: unless-stopped); if this persists, check "
                    "`docker ps` / `docker logs waha`.")
    else:
        _alert_once(status, f"WhatsApp gateway still {status} after auto-restart",
                    f"Auto-restart gave up after {AUTO_RESTART_MAX} attempts. A "
                    "manual re-pair (QR) is likely needed - open the Health page.")


def _email_alert(subject: str, body: str):
    if not (env.smtp_host and env.alert_email):
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[TaskWA] {subject}"
        msg["From"] = env.smtp_from or env.smtp_user
        msg["To"] = env.alert_email
        msg.set_content(body)
        with smtplib.SMTP(env.smtp_host, env.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if env.smtp_user:
                smtp.login(env.smtp_user, env.smtp_password)
            smtp.send_message(msg)
    except Exception as e:
        log.error("email alert failed: %s", e)


# ---------------- backup & retention ----------------
def nightly_backup():
    os.makedirs(env.backup_dir, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(env.backup_dir, f"tasks-{stamp}.db")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    # rotate: keep 14 newest
    backups = sorted(f for f in os.listdir(env.backup_dir)
                     if f.startswith("tasks-") and f.endswith(".db"))
    for old in backups[:-14]:
        os.remove(os.path.join(env.backup_dir, old))
    with session_scope() as s:
        set_setting(s, "last_backup", datetime.utcnow().isoformat(timespec="seconds"))
    log.info("backup written: %s", dest)


def purge_old():
    """Archive-then-delete completed/cancelled tasks older than N days."""
    with session_scope() as s:
        days = int(get_setting(s, "purge_after_days") or 30)
        cutoff = datetime.utcnow() - timedelta(days=days)
        old = (s.query(Task)
                .filter(Task.status.in_(("done", "cancelled")),
                        Task.updated_at < cutoff).all())
        if old:
            os.makedirs(env.backup_dir, exist_ok=True)
            archive = os.path.join(env.backup_dir, "archive.csv")
            new_file = not os.path.exists(archive)
            with open(archive, "a", newline="") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(["id", "title", "assignee", "priority", "status",
                                "due_date", "created_at", "completed_at"])
                for t in old:
                    w.writerow([t.id, t.title, t.assignee.name, t.priority,
                                t.status, t.due_date, t.created_at, t.completed_at])
            for t in old:
                s.query(StatusEvent).filter(StatusEvent.task_id == t.id).delete()
                s.delete(t)
            log.info("purged %d tasks (archived to %s)", len(old), archive)
        # housekeeping
        week_ago = datetime.utcnow() - timedelta(days=7)
        s.query(ProcessedMessage).filter(
            ProcessedMessage.processed_at < week_ago).delete()
        s.query(MessageLog).filter(MessageLog.created_at < cutoff).delete()


def latest_due_slot(now, times):
    """Most recent scheduled slot at or before `now` (tz-aware). Pure/testable."""
    candidates = []
    for t in times:
        try:
            hh, mm = t.strip().split(":")
            for day_off in (0, -1):
                slot = (now.replace(hour=int(hh), minute=int(mm),
                                    second=0, microsecond=0)
                        + timedelta(days=day_off))
                if slot <= now:
                    candidates.append(slot)
        except Exception:
            continue
    return max(candidates) if candidates else None


def startup_catchup():
    """Cold-boot catch-up: if the machine was OFF at a scheduled send time and
    the slot is less than 6 hours old, send the missed digest now. Guarded by
    last_send, so a digest that already went out is never repeated."""
    from zoneinfo import ZoneInfo as _ZI
    with session_scope() as s:
        tzname = get_setting(s, "timezone") or "UTC"
        times = get_setting(s, "send_times") or []
        last = get_setting(s, "last_send") or ""
        dry_note = get_setting(s, "dry_run")
    try:
        tz = _ZI(tzname)
    except Exception:
        tz = timezone.utc
    now = datetime.now(tz)
    slot = latest_due_slot(now, times)
    if slot is None or now - slot > timedelta(hours=6):
        return
    last_dt = None
    if last:
        try:
            last_dt = (datetime.fromisoformat(last)
                       .replace(tzinfo=timezone.utc).astimezone(tz))
        except ValueError:
            pass
    if last_dt is not None and last_dt >= slot:
        return  # that slot was already sent before shutdown
    log.info("startup catch-up: digest slot %s was missed while off - sending "
             "now (dry_run=%s)", slot.isoformat(), dry_note)
    send_daily_digests()


def reload_broadcast_jobs():
    """(Re)create one cron job per active, scheduled broadcast.
    No cold-boot catch-up on purpose: a missed 'good morning' should be
    skipped, not delivered at 3 PM."""
    import json as _json
    from .broadcasts import broadcast_tzname, days_to_cron, send_broadcast
    from .models import Broadcast
    for job in scheduler.get_jobs():
        if job.id.startswith(_BCAST_JOB_PREFIX):
            scheduler.remove_job(job.id)
    with session_scope() as s:
        fallback = get_setting(s, "timezone") or "UTC"
        rows = [(b.id, b.send_time, b.days, broadcast_tzname(b, fallback)) for b
                in s.query(Broadcast).filter(Broadcast.active.is_(True)).all()
                if b.send_time]
    jit = jitter_seconds()
    for bid, t, days_json, tzname in rows:
        try:
            tz = ZoneInfo(tzname)   # each broadcast fires in its pinned tz
            hh, mm = t.strip().split(":")
            dow = days_to_cron(_json.loads(days_json or "[]"))
            scheduler.add_job(send_broadcast, CronTrigger(
                day_of_week=dow, hour=int(hh), minute=int(mm), timezone=tz,
                jitter=jit or None),
                args=[bid], id=f"{_BCAST_JOB_PREFIX}{bid}",
                replace_existing=True,
                misfire_grace_time=300 + jit, coalesce=True)
        except Exception as e:
            log.error("bad broadcast schedule (id=%s, %r): %s", bid, t, e)
    log.info("broadcast jobs: %s", [j.id for j in scheduler.get_jobs()
                                    if j.id.startswith(_BCAST_JOB_PREFIX)])


def _resolve_test_admin(s):
    """Who test-mode sends redirect to. weekly_board_admin_id=0 means "auto":
    the lowest-id active admin (same default as the dashboard picker). A
    non-zero id that no longer resolves to an active admin is NOT silently
    swapped for a different one - the caller must skip the run instead."""
    from .models import Member
    chosen = int(get_setting(s, "weekly_board_admin_id") or 0)
    q = s.query(Member).filter(Member.role == "admin", Member.active.is_(True))
    if chosen:
        return q.filter(Member.id == chosen).first()
    return q.order_by(Member.id).first()


def send_weekly_boards():
    """Board snapshot to the team.

    RECIPIENT CONTRAST - READ BEFORE "FIXING": with test mode OFF this sends
    each member's board to THAT MEMBER'S OWN chat, and each group's board to
    THAT GROUP - real team-wide delivery. This is deliberately NOT the
    admin-preview path: do not route it through commands.build_board_previews()
    or otherwise redirect it to an admin. The preview/test-mode paths send to
    an admin ON PURPOSE; this one does not, and that difference is the point of
    the feature. Only weekly_board_test_mode=true redirects here.

    Test mode ON: every image goes to the configured admin instead (see
    _resolve_test_admin - defaults to the lowest-id active admin, or an
    explicitly chosen one from Settings), captioned with who it was really
    for, so the admin sees the exact per-recipient breakdown at zero risk to
    the team. Scheduling is gated by weekly_board_enabled AND at least one day
    being configured (see reload_board_jobs); test mode changes only the
    recipient, never whether the job runs."""
    from .board_render import render_member_board, render_group_board
    from .commands import _board_sub, _group_open_tasks, _recent_done_for
    from .engine import open_tasks_for
    from .models import Group, Member
    from .waha import chat_id_for_phone, send_image

    with session_scope() as s:
        if not get_setting(s, "weekly_board_enabled"):
            return
        test_mode = bool(get_setting(s, "weekly_board_test_mode"))
        admin_chat = None
        if test_mode:
            admin = _resolve_test_admin(s)
            if admin is None:
                log.warning("board snapshot: test mode on but the configured "
                            "admin isn't active (or none exists) - skipping "
                            "run to avoid a real team send")
                return
            admin_chat = chat_id_for_phone(admin.phone)
        members = s.query(Member).filter(Member.active.is_(True)).all()
        groups = s.query(Group).filter(Group.active.is_(True)).all()
        sends = []
        for m in members:
            tasks = open_tasks_for(s, m)
            done = _recent_done_for(s, m)
            if not tasks and not done:          # skip empty, like no-args preview
                continue
            png = render_member_board(m.name, _board_sub(tasks), tasks, done)
            if test_mode:
                sends.append((admin_chat, png,
                              f"Board snapshot test · would go to: {m.name}"))
            else:
                sends.append((chat_id_for_phone(m.phone), png,
                              "Your board snapshot"))
        for g in groups:
            gtasks = _group_open_tasks(s, g)
            if not gtasks:
                continue
            png = render_group_board(g.name, _board_sub(gtasks), gtasks)
            if test_mode:
                sends.append((admin_chat, png,
                              f"Board snapshot test · would go to: {g.name} (group)"))
            else:
                sends.append((g.chat_id, png, "Board snapshot"))
    # send_image throttles internally (3-8 s between sends); sequential is fine.
    for chat, png, cap in sends:
        send_image(chat, png, cap)
    log.info("board snapshot: sent %d image(s), test_mode=%s", len(sends), test_mode)


def reload_board_jobs():
    """(Re)create the board-snapshot cron. Registered ONLY when
    weekly_board_enabled is true AND at least one day is configured -
    disabled, or no days ticked, both mean no job exists at all. Days are
    capped at 2 defensively (settings_save is the primary guard - this is
    belt-and-suspenders in case a bad value ever reaches storage another way).
    A single CronTrigger fires on all configured days (APScheduler accepts a
    comma-joined day_of_week list). Test mode does NOT affect scheduling (only
    who receives the send), so enabled=true + test_mode=true still registers
    the job: that combination is the full risk-free rehearsal of the real
    cron path."""
    if scheduler.get_job(_BOARD_JOB_ID):
        scheduler.remove_job(_BOARD_JOB_ID)
    with session_scope() as s:
        if not get_setting(s, "weekly_board_enabled"):
            log.info("board snapshot job: disabled, not scheduled")
            return
        tz = ZoneInfo(get_setting(s, "timezone") or "UTC")
        days = [int(d) for d in (get_setting(s, "weekly_board_days") or [])
                if 0 <= int(d) <= 6]
        t = (get_setting(s, "weekly_board_time") or "08:05").strip()
    days = sorted(set(days))[:2]   # defensive cap; settings_save is primary guard
    if not days:
        log.info("board snapshot job: no days configured, not scheduled")
        return
    dow = ",".join(_DOW_NAMES[d] for d in days)
    jit = jitter_seconds()
    try:
        hh, mm = t.split(":")
        scheduler.add_job(send_weekly_boards, CronTrigger(
            day_of_week=dow, hour=int(hh), minute=int(mm),
            timezone=tz, jitter=jit or None),
            id=_BOARD_JOB_ID, replace_existing=True,
            misfire_grace_time=6 * 3600, coalesce=True)
        log.info("board snapshot job scheduled: %s %s tz=%s jitter=%ss",
                 dow, t, tz, jit)
    except Exception as e:
        log.error("bad board snapshot schedule (days=%r time=%r): %s",
                  days, t, e)


def run_broadcast_soon(broadcast_id: int):
    """Queue a one-shot Send-now so the dashboard request returns instantly
    (a 10-recipient broadcast takes minutes at broadcast pacing)."""
    from .broadcasts import send_broadcast
    scheduler.add_job(send_broadcast, "date",
                      run_date=datetime.now() + timedelta(seconds=2),
                      args=[broadcast_id],
                      id=f"bcast-now-{broadcast_id}-{datetime.utcnow().timestamp()}")


def expire_acceptance_dialogs():
    """No answer to 'Reply Y to accept, N to decline' within the window
    counts as ACCEPTED: record it in the audit trail and clear the queue.
    (Expired /add drafts are untouched - they die lazily as before.)"""
    import json as _json
    from .models import PendingConfirm
    with session_scope() as s:
        rows = (s.query(PendingConfirm)
                 .filter(PendingConfirm.expires_at < datetime.utcnow()).all())
        for p in rows:
            try:
                draft = _json.loads(p.draft_json)
            except ValueError:
                continue
            if draft.get("kind") != "accept":
                continue
            t = s.get(Task, draft.get("task_id"))
            if t is not None and t.status not in ("done", "cancelled"):
                s.add(StatusEvent(
                    task_id=t.id, actor_id=p.member_id,
                    from_status=t.status, to_status=t.status,
                    channel="system",
                    note="auto-accepted (no reply within 30 min)"))
                log.info("task #%s auto-accepted (assignee silent 30 min)", t.id)
            s.delete(p)


def start():
    reload_digest_jobs()
    reload_broadcast_jobs()
    reload_board_jobs()   # weekly kanban snapshot - only if weekly_board_enabled
    scheduler.add_job(check_gateway_health, "interval", minutes=5,
                      id="health", replace_existing=True,
                      next_run_time=datetime.utcnow())
    scheduler.add_job(expire_acceptance_dialogs, "interval", minutes=5,
                      id="accept-expiry", replace_existing=True)
    scheduler.add_job(nightly_backup, CronTrigger(hour=2, minute=30),
                      id="backup", replace_existing=True)
    scheduler.add_job(purge_old, CronTrigger(hour=3, minute=0),
                      id="purge", replace_existing=True)
    # cold-boot catch-up, delayed so the WhatsApp gateway is up first
    scheduler.add_job(startup_catchup, "date",
                      run_date=datetime.now() + timedelta(seconds=120),
                      id="catchup", replace_existing=True)
    scheduler.start()
    log.info("scheduler started")
