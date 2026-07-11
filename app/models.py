from datetime import datetime, date

from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer,
                        String, Text)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

STATUSES = ("open", "in_progress", "blocked", "done", "cancelled")
PRIORITIES = ("low", "medium", "high")


class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    phone = Column(String(20), unique=True, nullable=False)  # digits only, E.164 w/o '+'
    role = Column(String(10), default="member")              # admin | member
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    chat_id = Column(String(40), unique=True, nullable=False)  # xxxx@g.us
    active = Column(Boolean, default=True)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)  # serial number, global, never reused
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    assignee_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    creator_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    priority = Column(String(10), default="medium")
    post_to_group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    status = Column(String(15), default="open")
    blocker_reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    assignee = relationship("Member", foreign_keys=[assignee_id])
    creator = relationship("Member", foreign_keys=[creator_id])
    group = relationship("Group", foreign_keys=[post_to_group_id])

    @property
    def is_open(self):
        return self.status in ("open", "in_progress", "blocked")

    @property
    def blocked_days(self):
        if self.status != "blocked":
            return 0
        ev = sorted([e for e in self.events if e.to_status == "blocked"],
                    key=lambda e: e.created_at)
        if not ev:
            return 0
        return (datetime.utcnow() - ev[-1].created_at).days


class StatusEvent(Base):
    __tablename__ = "status_events"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    actor_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    from_status = Column(String(15))
    to_status = Column(String(15))
    note = Column(Text, default="")
    channel = Column(String(15), default="system")  # whatsapp | dashboard | system
    raw_text = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", backref="events")
    actor = relationship("Member")


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(50), primary_key=True)
    value = Column(Text, nullable=False)


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"
    message_id = Column(String(120), primary_key=True)
    processed_at = Column(DateTime, default=datetime.utcnow)


class PendingConfirm(Base):
    __tablename__ = "pending_confirms"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), unique=True, nullable=False)
    draft_json = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class ResetCode(Base):
    __tablename__ = "reset_codes"
    id = Column(Integer, primary_key=True)
    code_hash = Column(String(200), nullable=False)
    expires_at = Column(DateTime, nullable=False)


class MessageLog(Base):
    __tablename__ = "message_log"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String(40))
    text = Column(Text)
    status = Column(String(10))  # dryrun | sent | failed
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class DigestRef(Base):
    """Maps the small numbers shown in a member's digest (1, 2, 3...) to real
    task serials. Rebuilt on every digest send and /mytasks."""
    __tablename__ = "digest_refs"
    id = Column(Integer, primary_key=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    pos = Column(Integer, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class GroupDigestRef(Base):
    """Maps the numbers shown in a GROUP digest (1, 2, 3...) to task serials.
    Rebuilt on every group digest send."""
    __tablename__ = "group_digest_refs"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    pos = Column(Integer, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Broadcast(Base):
    """A scheduled plain message - sent verbatim, no digest formatting."""
    __tablename__ = "broadcasts"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    message = Column(Text, nullable=False)
    member_ids = Column(Text, default="[]")   # JSON list of member ids
    group_ids = Column(Text, default="[]")    # JSON list of group ids
    days = Column(Text, default="[]")         # JSON list of ints, 0=Mon .. 6=Sun
    send_time = Column(String(5), default="") # "HH:MM", empty = manual only
    tz = Column(String(64), default="")       # IANA tz, pinned at save time;
                                              # "" = legacy row -> stamped at startup
    active = Column(Boolean, default=True)
    last_sent = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
