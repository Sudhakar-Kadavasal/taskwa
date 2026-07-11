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


def reload_digest_jobs():
    """(Re)create one cron job per configured send time."""
    for job in scheduler.get_jobs():
        if job.id.startswith(_DIGEST_JOB_PREFIX):
            scheduler.remove_job(job.id)
    with session_scope() as s:
        tz = ZoneInfo(get_setting(s, "timezone") or "UTC")
        times = get_setting(s, "send_times") or ["08:00"]
    for t in times:
        try:
            hh, mm = t.strip().split(":")
            scheduler.add_job(send_daily_digests, CronTrigger(
                hour=int(hh), minute=int(mm), timezone=tz),
                id=f"{_DIGEST_JOB_PREFIX}{t}", replace_existing=True,
                misfire_grace_time=6 * 3600, coalesce=True)
        except Exception as e:
            log.error("bad send time %r: %s", t, e)
    log.info("digest jobs: %s", [j.id for j in scheduler.get_jobs()
                                 if j.id.startswith(_DIGEST_JOB_PREFIX)])


# ---------------- health ----------------
_last_alerted_status = {"value": None}


def check_gateway_health():
    status = session_status()
    with session_scope() as s:
        prev = get_setting(s, "gateway_status")
        set_setting(s, "gateway_status", status)
        set_setting(s, "gateway_status_at",
                    datetime.utcnow().isoformat(timespec="seconds"))
    if env.healthchecks_url and status == "WORKING":
        try:
            httpx.get(env.healthchecks_url, timeout=10)
        except Exception:
            pass
    if status != "WORKING" and prev == "WORKING" \
            and _last_alerted_status["value"] != status:
        _last_alerted_status["value"] = status
        _email_alert(f"WhatsApp gateway session is {status}",
                     "The task-manager gateway session is no longer WORKING.\n"
                     "Open the dashboard Health page and re-pair via QR if needed.")
    if status == "WORKING":
        _last_alerted_status["value"] = None
        if prev != "WORKING":
            # populate WAHA's lid->phone map so group replies resolve
            try:
                from .waha import list_groups
                list_groups()
            except Exception as e:
                log.warning("lid warmup failed: %s", e)


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
    for bid, t, days_json, tzname in rows:
        try:
            tz = ZoneInfo(tzname)   # each broadcast fires in its pinned tz
            hh, mm = t.strip().split(":")
            dow = days_to_cron(_json.loads(days_json or "[]"))
            scheduler.add_job(send_broadcast, CronTrigger(
                day_of_week=dow, hour=int(hh), minute=int(mm), timezone=tz),
                args=[bid], id=f"{_BCAST_JOB_PREFIX}{bid}",
                replace_existing=True, misfire_grace_time=300, coalesce=True)
        except Exception as e:
            log.error("bad broadcast schedule (id=%s, %r): %s", bid, t, e)
    log.info("broadcast jobs: %s", [j.id for j in scheduler.get_jobs()
                                    if j.id.startswith(_BCAST_JOB_PREFIX)])


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
