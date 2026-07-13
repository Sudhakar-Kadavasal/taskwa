# -*- coding: utf-8 -*-
"""TaskWA User Manual — ships in repo docs/."""
from dg_common import *

import os
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "TaskWA-User-Manual.pdf")


def cover(cv):
    cv.setFillColor(ORANGE); cv.rect(0, PAGE_H-1.1*cm, PAGE_W, 1.1*cm, stroke=0, fill=1)
    cv.setFillColor(ORANGE); cv.setFont("Serif-Bold", 46)
    cv.drawString(ML, PAGE_H-6.6*cm, "TaskWA")
    cv.setFillColor(INK); cv.setFont("Serif-Bold", 22)
    cv.drawString(ML, PAGE_H-7.9*cm, "User Manual")
    cv.setFillColor(CHAR); cv.setFont("Serif", 11.5)
    cv.drawString(ML, PAGE_H-9.0*cm,
                  "Everything your team needs in two pages — and everything the")
    cv.drawString(ML, PAGE_H-9.55*cm, "administrator needs in the rest.")
    cv.setStrokeColor(INK); cv.setLineWidth(1.2)
    cv.line(ML, PAGE_H-10.3*cm, ML+7*cm, PAGE_H-10.3*cm)
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 9)
    cv.drawString(ML, PAGE_H-11.0*cm, "Version 1.6  ·  July 2026")
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 7.8)
    cv.drawString(ML, 1.9*cm, "Part I — For team members      "
                              "Part II — For the administrator")


doc = make_doc(OUT, "TaskWA User Manual · v1.6", "User Manual", cover)
E = []
start_body(E)

# ================= PART I =================
E += section("I", "For team members — the only pages you need")
E.append(P("TaskWA sends you one WhatsApp message each morning with your open tasks. "
           "You reply in the same chat. That's the whole system.", "lede"))

E.append(P("<b>Your morning message looks like this:</b>", "bodyL"))
E.append(chat_bubble([
 "Good morning, Ravi - 3 open tasks today:",
 "",
 "  1. [HIGH] Send Q2 invoice to Alpha LLC  - due Fri 17 Jul",
 "  2. Buy cement for Site B  - due today",
 "  [!] 3. Fix generator - BLOCKED 2d: waiting on supplier quote",
 "",
 "Reply:  1 done  |  1 in progress  |  1 block &lt;reason&gt;"]))
E.append(Spacer(1, 6))
E.append(P("<b>Replying — use the number from the list, then the word:</b>", "bodyL"))
E.append(table(["You send", "What happens"],
    [[Paragraph("<font face='Mono-Bold'>1 done</font>", S["tcell"]),
      "Task 1 is closed. You get a thumbs-up reaction as confirmation."],
     [Paragraph("<font face='Mono-Bold'>2 in progress</font>", S["tcell"]),
      "Task 2 is marked started."],
     [Paragraph("<font face='Mono-Bold'>3 block waiting on quote</font>", S["tcell"]),
      "Task 3 is marked blocked with your reason, and the admin is told immediately. "
      "Always include the reason."],
     [Paragraph("<font face='Mono-Bold'>3 block waiting on @Priya</font>", S["tcell"]),
      "Same, but the block is handed to Priya: she gets one message telling her "
      "you're waiting on her, with instructions to release it."],
     [Paragraph("<font face='Mono-Bold'>3 unblock</font>", S["tcell"]),
      "You release a block that waits on YOU (your part is done, or there is no "
      "block on your side). The task flips back to in-progress and its owner is told."],
     [Paragraph("<font face='Mono-Bold'>1 reopen</font>", S["tcell"]),
      "Made a mistake? This reopens a task you closed."],
     [Paragraph("<font face='Mono-Bold'>done</font>", S["tcell"]),
      "If you have only one open task, no number is needed."]],
    [4.3*cm, FW-4.3*cm]))
E.append(Spacer(1, 4))
E.append(P("<b>Even easier — swipe to reply.</b> Swipe (long-press → Reply) on the task's "
           "message and just type <font face='Mono-Bold'>done</font>. The bot knows which "
           "task you mean."))
E.append(P("<b>See your list any time:</b> send <font face='Mono-Bold'>/mytasks</font>. "
           "<b>Confused?</b> Send <font face='Mono-Bold'>/help</font>."))

E.append(P("Creating a task", "h2"))
E.append(P("Send /add with a title. Mention someone to assign it to them; add "
           "<font face='Mono'>!high</font> or <font face='Mono'>!low</font> for priority; "
           "end with a date word — today, tomorrow, fri, or 25/07:"))
E.append(chat_bubble(["/add Send Q2 invoice @Priya fri !high"], sender="me", width=FW*0.6))
E.append(chat_bubble(['Create task: "Send Q2 invoice" -> Priya,',
                      "due Fri 17 Jul, high priority?",
                      "Reply Y to confirm, N to cancel."], width=FW*0.6))
E.append(Spacer(1, 4))
E.append(P("Reply <font face='Mono-Bold'>y</font> and it's created. Nothing is created "
           "without your confirmation. In a group, the task shows up in that group's "
           "daily list; otherwise <b>the assignee is told immediately</b> (next section)."))

E.append(P("When a task is created FOR you", "h2"))
E.append(P("The moment someone assigns you a task, you get a message — no waiting for "
           "tomorrow's digest:"))
E.append(chat_bubble(["New task from Sudhakar: Send Q2 invoice,",
                      "due Fri 17 Jul",
                      "",
                      "Reply Y to accept, N to decline",
                      "(no reply in 30 min counts as accepted).",
                      "",
                      "Reply:  7 done  |  7 in progress",
                      "        |  7 block &lt;reason&gt;"], width=FW*0.66))
E.append(Spacer(1, 4))
E.append(P("<font face='Mono-Bold'>Y</font> accepts. <font face='Mono-Bold'>N</font> "
           "sends the task straight back to whoever created it — it never just "
           "disappears. Say nothing for 30 minutes and it counts as accepted. The "
           "number in the message (the task's permanent #) works right away."))
E.append(P("<b>Created it yourself?</b> The creator keeps two powers over their own "
           "task even after it's assigned: <font face='Mono-Bold'>7 done</font> closes "
           "it, <font face='Mono-Bold'>7 cancel &lt;reason&gt;</font> cancels it — the "
           "assignee gets one notice either way. Everything else (starting, blocking) "
           "stays with the assignee."))

E.append(P("Waiting on a teammate? Hand them the block", "h2"))
E.append(P("Stuck because someone else must act first? Name them with an @ and the bot "
           "runs the follow-up for you:"))
E.append(chat_bubble(["3 block waiting on @Priya"], sender="me", width=FW*0.55))
E.append(chat_bubble(["Priya - Ravi is waiting on you for task #3:",
                      "Fix generator",
                      "Reason: waiting on @Priya",
                      "",
                      "Reply:  3 unblock  - when your part is done,",
                      "or if there's no block on your side."], width=FW*0.72))
E.append(Spacer(1, 4))
E.append(P("Priya's <font face='Mono-Bold'>3 unblock</font> flips the task back to "
           "in-progress and tells Ravi it's on him again. Until then her own morning "
           "digest reminds her under <b>Waiting on you</b>. She can release the block, "
           "but she cannot close Ravi's task."))
E.append(callout("<b>Good to know:</b> only you (or an admin) can close your tasks — a "
                 "teammate can't mark your work done. The bot never reads receipts, never "
                 "replies to normal conversation, and stays completely silent in chats "
                 "that aren't registered."))
E.append(PageBreak())

# ================= PART II =================
E += section("II", "For the administrator")
E.append(P("You run TaskWA from the dashboard at <font face='Mono'>http://localhost:3000</font> "
           "on the machine where it is installed. Log in with the admin password.", "lede"))

E.append(P("Members", "h2"))
E.append(P("Register each person with a name and their WhatsApp number (country code + "
           "number, digits only — e.g. 9715xxxxxxxx). The number IS their identity: messages "
           "from any other number are ignored silently. Roles: <b>admin</b> receives blocker "
           "alerts and can update anyone's task; <b>member</b> manages only their own. "
           "Deactivating a member stops their digests and their commands instantly — reassign "
           "their open tasks first from the Tasks page."))
E.append(P("<b>The fast way — import from a group.</b> Members page → <b>Import from "
           "group</b> → pick a registered group: every participant appears in a table with "
           "their name and number pre-filled. Tick the ones you want, fix names, click "
           "Import — done. Participants whose numbers WhatsApp hides (privacy settings) "
           "are shown with the remedy: save them as a contact, or make the bot's number a "
           "group admin, and re-detect."))

E.append(P("Groups", "h2"))
E.append(P("Add the bot's WhatsApp number to the group, then click <b>Detect my groups</b> on "
           "the Groups page — every group the number belongs to appears with a one-click "
           "Register button. Only registered groups are listened to; everything else stays "
           "private. Tasks flagged 'post to group' (or created via /add inside the group) "
           "appear in that group's daily digest instead of the assignee's personal one."))

E.append(P("Broadcasts — your own plain messages, on a schedule", "h2"))
E.append(P("Broadcasts send <b>exactly the text you type</b> to chosen members and "
           "groups — no task numbers, no headers, no reply footer. Recipients see an "
           "ordinary WhatsApp message from you. Use them for the daily good-morning, "
           "status nudges, or anything that isn't a task."))
E.append(table(["On the Broadcasts page", "Notes"],
    [["Message text", "Sent verbatim. {date} becomes '11 July 2026', {day} becomes "
      "'Friday'. WhatsApp *bold* and _italic_ work."],
     ["Days + send time", "Tick weekdays and set a time — or leave the time empty for a "
      "manual-only broadcast you fire with Send now."],
     ["Time zone", "Each broadcast has its own timezone dropdown (defaults to the "
      "dashboard setting) and is PINNED to it when saved — changing the dashboard "
      "timezone later never moves an existing broadcast."],
     ["Recipients", "Any registered members and groups. To message someone who isn't on "
      "the task team, register them as a member — with no tasks they'll never get "
      "digests, only your broadcasts."],
     ["Pacing", "Recipients are messaged 20–45 seconds apart and never overlap other "
      "TaskWA sends — ban-risk hygiene. A missed send (machine off) is deliberately "
      "skipped, not delivered late."]],
    [3.6*cm, FW-3.6*cm]))

E.append(P("Settings that matter", "h2"))
E.append(table(["Setting", "Meaning"],
    [["Timezone & send times", "IANA timezone (e.g. Asia/Dubai) and one or more daily "
      "digest times, comma-separated (08:00, 17:00)."],
     ["Acknowledgment mode", "reaction (thumbs-up on the message — recommended), reply (a text "
      "'Noted.'), or silent."],
     ["Personal number mode", "ON when the bot shares your own WhatsApp number. The bot "
      "then never replies to anything that isn't a command, your private chats are never "
      "touched, and your own digest arrives in 'Message Yourself'."],
     ["Dry-run", "The safety switch: ON means every message is logged on the Health page "
      "instead of being sent. Use it whenever you experiment."],
     ["Hourly cap / retention", "Upper bound on messages per hour (ban-risk hygiene) and "
      "days before completed tasks are archived to CSV and purged (default 30)."]],
    [3.6*cm, FW-3.6*cm]))

E.append(P("The Health page — your first stop when anything seems wrong", "h2"))
E.append(table(["Status", "What to do"],
    [["WORKING", "All good. Check 'last digest' and 'last backup' times occasionally."],
     ["SCAN_QR_CODE", "The WhatsApp pairing dropped. Click Start session if needed, scan "
      "the QR with the bot number's phone (WhatsApp → Linked devices), refresh."],
     ["STARTING", "Be patient — 30–60 seconds on Apple Silicon."],
     ["FAILED / STOPPED", "Click Start / restart session. If it fails repeatedly, restart "
      "the gateway container (see Installation Guide, Troubleshooting)."],
     ["UNREACHABLE", "The gateway container isn't running — usually right after a reboot; "
      "wait a minute. Persisting: docker compose up -d from the install folder."]],
    [3.0*cm, FW-3.0*cm]))
E.append(P("The message log at the bottom shows every outbound message with its status — "
           "including <b>dryrun</b> (not sent, dry-run on), <b>failed</b> (gateway error, "
           "shown), and <b>blocked</b> (recipient not registered — the allowlist refused it, "
           "which is the system protecting you)."))

E.append(P("Routine care", "h2"))
for b in [
 "<b>Backups are automatic</b> — nightly database snapshots, 14 kept, in the backups folder. To restore: stop the app, copy a snapshot over data/tasks.db, start again.",
 "<b>Exports</b> — tasks.csv and audit.csv from the Tasks page, any time.",
 "<b>Forgotten password</b> — 'Forgot password' on the login page sends a 6-digit code to your WhatsApp. If WhatsApp itself is down: docker compose exec app python -m app.cli reset-password",
 "<b>Upgrades</b> — see docs/UPGRADE.md; in short: git pull, docker compose up -d --build. Data survives.",
 "<b>Survive restarts automatically</b> — run the one-command autostart installer for your OS (scripts/autostart-macos.sh, autostart-windows.ps1, sudo autostart-linux.sh): at every login/boot it starts Docker, waits for the engine, and brings TaskWA up. Full four-link chain (auto power-on, auto-login, Docker, containers) in docs/UNATTENDED.md.",
 "<b>Keep the machine awake</b> — a sleeping laptop sends no digests. Digests missed by under 6 hours send on wake; missed broadcasts are skipped on purpose.",
]:
    E.append(P("•  " + b, "bullet"))
E.append(Spacer(1, 4))
E.append(callout("<b>The one standing risk, stated plainly:</b> TaskWA uses an unofficial "
                 "WhatsApp gateway. WhatsApp can ban the paired number without notice. Keep "
                 "volumes modest, keep the hourly cap on, and understand that on a personal "
                 "number, the ban risk is to your personal account. Your task data is never "
                 "at risk — only the delivery channel."))

doc.build(E)
print("OK manual")
