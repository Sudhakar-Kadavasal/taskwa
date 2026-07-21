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
    cv.drawString(ML, PAGE_H-11.0*cm, "Version 1.7  ·  July 2026")
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 7.8)
    cv.drawString(ML, 1.9*cm, "Part I — For team members      "
                              "Part II — For the administrator")


doc = make_doc(OUT, "TaskWA User Manual · v1.7", "User Manual", cover)
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

E.append(P("See it as a picture — /board", "h2"))
E.append(P("Sometimes a list isn't enough. Send <font face='Mono-Bold'>/board</font> "
           "(or <font face='Mono-Bold'>/myboard</font>) and TaskWA replies with an "
           "image — your own tasks laid out as a board: Blocked, In progress, "
           "To do, and what you finished in the last 7 days. It's yours alone; "
           "nobody else's tasks appear on it, and nobody else can pull yours "
           "except an admin naming you on purpose (next part)."))
E.append(P("Creating a task", "h2"))
E.append(P("Send /add with a title. Mention someone to assign it to them; add "
           "<font face='Mono'>!high</font> or <font face='Mono'>!low</font> for priority; "
           "add <font face='Mono'>#group</font> to post it to a registered group "
           "(any part of the group's name works — <font face='Mono'>#site</font> finds "
           "'Site B Construction'; for a space, dot it or quote it — next section); "
           "end with a date word — today, tomorrow, fri, or 25/07:"))
E.append(chat_bubble(["/add Send Q2 invoice @Priya fri !high"], sender="me", width=FW*0.6))
E.append(chat_bubble(['Create task: "Send Q2 invoice" -> Priya,',
                      "due Fri 17 Jul, high priority?",
                      "Reply Y to confirm, N to cancel."], width=FW*0.6))
E.append(Spacer(1, 4))
E.append(P("Reply <font face='Mono-Bold'>y</font> and it's created. Nothing is created "
           "without your confirmation. In a group, the task shows up in that group's "
           "daily list; otherwise <b>the assignee is told immediately</b> (next section)."))
E.append(P("<b>Created it with a #group tag?</b> On your Y the bot posts one "
           "announcement in that group — \"New task for Ravi: …\" with the reply "
           "numbers — so you instantly see it reached the right place. You must be a "
           "member of that group yourself (admins are exempt); if WhatsApp privacy "
           "settings prevent verifying the member list, the task is refused rather "
           "than guessed."))
E.append(P("<b>Track what you've delegated:</b> send <font face='Mono-Bold'>/myadd"
           "</font> — every open task you created for someone else, with its status, "
           "age of any block, and the reminder that you can close or cancel each one."))

E.append(P("Names with a space — dot it or quote it", "h2"))
E.append(P("WhatsApp doesn't tell the bot where a typed name ends, so a name with a "
           "space needs one of two marks: a <b>dot in place of the space</b>, or "
           "<b>quotes around the whole name</b>. Both work everywhere a name or a "
           "group can appear — <font face='Mono'>/add</font>, "
           "<font face='Mono'>/nudge</font>, and <font face='Mono'>block waiting on</font>."))
E.append(table(["You type", "Who it means"],
    [[Paragraph("<font face='Mono-Bold'>@Ravi.Shankar</font>", S["tcell"]),
      "Ravi Shankar. The dot stands for the space — shortest to type, never "
      "ambiguous."],
     [Paragraph("<font face='Mono-Bold'>@\"Ravi Shankar\"</font>", S["tcell"]),
      "The same person, written naturally. Your phone's curly quotes "
      "(<font face='Mono'>“ ”</font>) are understood too — you don't have to fight "
      "autocorrect."],
     [Paragraph("<font face='Mono-Bold'>@Ravi</font>", S["tcell"]),
      "Also Ravi Shankar, as long as no one else on the team starts with 'Ravi'. "
      "If it's ambiguous the bot says so rather than guessing."],
     [Paragraph("<font face='Mono-Bold'>@Ravi Shankar</font>", S["tcell"]),
      "Understood as well — the bot joins the words back into a name. It works, but "
      "the dot or the quotes are the forms that can never be misread."],
     [Paragraph("<font face='Mono-Bold'>#site.b</font>  ·  "
                "<font face='Mono-Bold'>#\"Site B\"</font>  ·  "
                "<font face='Mono-Bold'>#Site B</font>", S["tcell"]),
      "The group 'Site B Construction'. Groups follow exactly the same three rules "
      "as names — dot, quotes, or plain spaces — and any unique part of the group's "
      "name is enough. If the tag matches two groups the bot asks you to be more "
      "specific rather than guessing."]],
    [4.3*cm, FW-4.3*cm]))
E.append(Spacer(1, 4))
E.append(P("Tapping WhatsApp's own @-mention picker always works as well — the bot "
           "resolves the number behind it."))

E.append(P("Two people with similar names? The bot asks", "h2"))
E.append(P("If what you typed could mean more than one person, the bot does not "
           "guess — <b>it lists them and asks you to pick a number</b>. The same "
           "happens if you mistype a name (it offers the closest matches), and if "
           "a <font face='Mono'>#tag</font> matches two groups."))
E.append(chat_bubble(["/add Fix the pump @Ravi tomorrow !high"], sender="me",
                     width=FW*0.62))
E.append(chat_bubble(["'@Ravi' matches 2 people:",
                      "  1. Ravi Shankar  (...0002)",
                      "  2. Ravi Kumar  (...0045)",
                      "",
                      "Reply with the number. Anything else cancels this",
                      "and is read as a new message."], width=FW*0.72))
E.append(chat_bubble(["2"], sender="me", width=FW*0.2))
E.append(chat_bubble(['Create task: "Fix the pump" -> Ravi Kumar,',
                      "due Wed 15 Jul, high priority?",
                      "Reply Y to confirm, N to cancel."], width=FW*0.62))
E.append(Spacer(1, 4))
E.append(P("The rest of your message survives the detour — the title, the date and "
           "the priority are all carried through, and you carry on with the normal "
           "<font face='Mono-Bold'>Y</font>. The last four digits of each number are "
           "shown so you can tell two same-named people apart. <b>Only a bare number "
           "answers the question</b>: <font face='Mono-Bold'>2 done</font> still means "
           "'task 2 is done', and anything else simply drops the question and is read "
           "as a new message."))

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
           "on the machine where it is installed. Log in with the admin password. "
           "This part walks the dashboard page by page, then covers "
           "troubleshooting and routine care.", "lede"))

E.append(P("The Tasks page — your daily driver", "h2"))
E.append(P("The front page lists tasks with filters for status and assignee "
           "(the default view is everything still open). Each row shows the "
           "task's permanent # number, blocker details in red, and the group "
           "it posts to. Under <b>Actions</b>:"))
E.append(table(["Control", "What it does"],
    [["✓ Done  /  ✗ Cancel", "One click closes or cancels the task (Cancel asks "
      "for confirmation). The assignee gets one WhatsApp notice that it's off "
      "their list — in the task's group if it has one, else a DM. No notice "
      "when the assignee is an admin."],
     ["Status dropdown + Set", "Any other transition — reopen, in progress, "
      "blocked (type the reason in the note box first). An impossible change "
      "shows a red banner explaining why instead of failing silently."],
     ["edit", "Expand to change title, assignee, priority, due date, "
      "description or group posting."],
     ["New task (below the list)", "Create a task from the browser — the "
      "assignee gets the same instant accept/decline message as with /add."]],
    [4.2*cm, FW-4.2*cm]))
E.append(P("Exports live at the bottom of the page: <b>tasks.csv</b> (current "
           "data) and <b>audit.csv</b> (every status change ever, with who, "
           "when and the raw message text)."))

E.append(P("Members", "h2"))
E.append(P("Register each person with a name and their WhatsApp number (country code + "
           "number, digits only — e.g. 9715xxxxxxxx). The number IS their identity: messages "
           "from any other number are ignored silently. Roles: <b>admin</b> receives blocker "
           "alerts and can update anyone's task; <b>member</b> manages only their own. "
           "Deactivating a member stops their digests and their commands instantly — reassign "
           "their open tasks first from the Tasks page. <b>Change a member's role any time</b> "
           "with the dropdown in their row (it saves on selection). Promotion to admin is "
           "deliberately dashboard-only — no chat command can do it — and the last active "
           "admin cannot be demoted: promote a successor first."))
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

E.append(P("The Board page — kanban view (new in v1.7)", "h2"))
E.append(P("Dashboard → Board shows every open task as four columns — To do, "
           "In progress, Blocked, Done (last 7 days only, so it doesn't grow "
           "forever) — with a per-assignee filter. It's read-only: a "
           "quick shape-of-the-work view, not a second place to edit tasks. "
           "While v1.7 is new, the page carries an amber 'in development' "
           "banner as a heads-up that layout may still change."))
E.append(P("<b>Preview before anyone sees anything.</b> The same page has a "
           "<b>Preview selected boards</b> panel — tick any members and/or "
           "groups, pick which admin should receive it (if there's more than "
           "one admin), click send: the rendered board images go to that "
           "admin's own WhatsApp chat only. Nothing goes to the team. Use "
           "this to see exactly what a member's board image looks like "
           "before turning anything on for real. The same thing is available "
           "from WhatsApp as <font face='Mono-Bold'>/board preview @Name"
           "</font> (admin-only, DM-only; no name previews everyone)."))
E.append(P("<b>Board snapshot — an optional picture on a schedule.</b> "
           "Settings can turn on a recurring send of each person's board "
           "image, on up to two chosen days a week, at a set time. It ships "
           "<b>off by default</b> — nothing goes out until you turn it on. "
           "There is also a <b>test mode</b>: with test mode on, the real "
           "schedule fires for real (proving the day/time actually works) "
           "but every image is redirected to one admin instead of the team, "
           "captioned with who it would really have gone to. The intended "
           "order: turn it on with test mode on and a near-term time, confirm "
           "the images look right, turn test mode off for exactly one real "
           "send to the team as a final check, then set the schedule you "
           "actually want and leave test mode off."))

E.append(P("Nudger — your own plain messages, on a schedule", "h2"))
E.append(P("The Nudger sends <b>exactly the text you type</b> to chosen members and "
           "groups — no task numbers, no headers, no reply footer: polite nudging "
           "without seeming like an assigned task. Recipients and groups see an "
           "ordinary WhatsApp message from you. Use it for the daily good-morning, "
           "status follow-ups, or anything that isn't a task. Manage nudges here on "
           "the dashboard, or entirely from WhatsApp with /nudge (next section)."))
E.append(table(["On the Nudger page", "Notes"],
    [["Message text", "Sent verbatim. {date} becomes '11 July 2026', {day} becomes "
      "'Friday'. WhatsApp *bold* and _italic_ work."],
     ["Days + send time", "Tick weekdays and set a time — or leave the time empty for a "
      "manual-only nudge you fire with Send now."],
     ["Time zone", "Each nudge has its own timezone dropdown (defaults to the "
      "dashboard setting) and is PINNED to it when saved — changing the dashboard "
      "timezone later never moves an existing nudge."],
     ["Recipients", "Any registered members and groups. To message someone who isn't on "
      "the task team, register them as a member — with no tasks they'll never get "
      "digests, only your nudges."],
     ["Pacing", "Recipients are messaged 20–45 seconds apart and never overlap other "
      "TaskWA sends — ban-risk hygiene. A missed send (machine off) is deliberately "
      "skipped, not delivered late."]],
    [3.6*cm, FW-3.6*cm]))

E.append(P("Admin commands over WhatsApp — no dashboard needed", "h2"))
E.append(P("Admins can run the essentials from their phone by <b>DM'ing the bot "
           "directly</b> (on a personal-number install that means your own "
           "'Message Yourself' chat). These commands are ignored in groups and "
           "refused for non-admins; anything that creates or deletes asks Y/N "
           "first. No AI involved — fixed wording, options first, message last."))
E.append(table(["Command", "What it does"],
    [[Paragraph("<font face='Mono-Bold'>/nudge 07:30 tue @Ravi.Shankar #site "
                "What is the status?</font>", S["tcell"]),
      "Create a nudge: the time is <b>required</b> — without one the bot asks for "
      "it rather than creating a nudge that never fires. Write it however you "
      "like: <font face='Mono'>07:30 · 7:30 · 730 · 0730 · 7.30 · 7:30am · 730pm "
      "· 7am</font> all mean the same thing. (A bare <font face='Mono'>3</font> is "
      "read as a nudge <i>number</i>, not 3 o'clock — write 3pm or 15:00.) Then "
      "days (or 'daily' / omit = every day), @Name members and #group targets, "
      "then the message, sent verbatim. <b>A name with a space is dotted or "
      "quoted</b> — @Ravi.Shankar or @\"Ravi Shankar\". Timezone pins to the "
      "dashboard setting. Manual-only nudges (no time) can still be made on the "
      "dashboard."],
     [Paragraph("<font face='Mono-Bold'>/nudges</font>", S["tcell"]),
      "Numbered list of every nudge with schedule, recipients and "
      "active/paused state."],
     [Paragraph("<font face='Mono-Bold'>/nudge 3 08:15 tue,thu</font>", S["tcell"]),
      "Reschedule nudge 3 — time, days and/or recipients. The text never "
      "changes this way: delete and recreate, or use the dashboard."],
     [Paragraph("<font face='Mono-Bold'>/nudge off 3   /nudge on 3</font>", S["tcell"]),
      "Pause / resume instantly (reversible, so no confirmation)."],
     [Paragraph("<font face='Mono-Bold'>/nudge delete 3</font>", S["tcell"]),
      "Delete after a Y/N confirmation."],
     [Paragraph("<font face='Mono-Bold'>/adduser 971501234567 Ravi Kumar</font>",
                S["tcell"]),
      "Register a member (spaces and + in the number are fine). Always "
      "role 'member' — promoting to admin stays a dashboard-only act. "
      "Re-adding an inactive number reactivates it. CHECK THE NUMBER in "
      "the Y/N prompt: a typo would register a stranger."],
     [Paragraph("<font face='Mono-Bold'>/rename @Ravi Ravi Shankar</font>",
                S["tcell"]),
      "Change the name TaskWA shows for someone — the name the team reads in "
      "group announcements ('New task for …'), digests and blocker alerts. It "
      "is <b>not</b> your phone's contact name, and editing it here does not "
      "touch your contacts. Y/N confirmed. Two members can never share a name: "
      "the name is how people are addressed (@Ravi), so a duplicate would make "
      "'@Ravi' ambiguous and work could land on the wrong person — the bot "
      "refuses. Same thing inline on the dashboard's Members page."],
     [Paragraph("<font face='Mono-Bold'>/members</font>", S["tcell"]),
      "List everyone registered, with roles and inactive flags."],
     [Paragraph("<font face='Mono-Bold'>/board preview @Ravi.Shankar "
                "#Site.B</font>", S["tcell"]),
      "Render the named member(s)/group(s) board(s) and send them to YOUR "
      "own WhatsApp only — never the team. Leave off the names to preview "
      "everyone at once. Same feature as the dashboard's Preview panel, "
      "for when you're on your phone."],
     [Paragraph("<font face='Mono-Bold'>/help</font>", S["tcell"]),
      "Role-aware: members see member commands; admins (in DM) also get "
      "this admin section."]],
    [5.2*cm, FW-5.2*cm]))

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
     ["SCAN_QR_CODE", "WhatsApp logged the number out — only a scan fixes it. Click "
      "Re-pair (new QR), scan with the bot number's phone (WhatsApp → Linked devices), "
      "refresh."],
     ["STARTING", "Be patient — 30–60 seconds on Apple Silicon."],
     ["FAILED / STOPPED", "The engine crashed or stopped, but the pairing is still good. "
      "Click Restart gateway session — it restarts the session with no QR. If it keeps "
      "failing, restart the container (see Installation Guide, Troubleshooting)."],
     ["UNREACHABLE", "The gateway container isn't running — usually right after a reboot; "
      "Docker brings it back on its own within a minute. Persisting: docker compose up -d "
      "from the install folder."]],
    [3.0*cm, FW-3.0*cm]))
E.append(P("The message log at the bottom shows every outbound message with its status — "
           "including <b>dryrun</b> (not sent, dry-run on), <b>failed</b> (gateway error, "
           "shown), and <b>blocked</b> (recipient not registered — the allowlist refused it, "
           "which is the system protecting you)."))

E.append(P("When the session fails — restart vs re-pair", "h2"))
E.append(P("A failed session is one of two things, and the two Health-page buttons match "
           "them. <b>Most failures are just a crashed engine</b> — the WhatsApp pairing "
           "saved on your disk is still valid, so a plain restart brings it back with no QR. "
           "Press <b>Restart gateway session</b>; it restarts the session with the pairing "
           "intact and fixes most FAILED/STOPPED cases and stuck sends. Recovery is "
           "deliberately manual — a click, never automatic — because repeatedly restarting a "
           "personal WhatsApp number is itself a ban signal. <b>The other kind is a real "
           "logout</b> — WhatsApp dropped the linked device (the phone was off for days, or "
           "the bot's number was opened in WhatsApp Web/Desktop somewhere else). No restart "
           "can fix that; it needs a fresh scan, so use <b>Re-pair (new QR)</b> and scan. "
           "<b>The quick tell:</b> press Restart gateway session and if a QR still appears, "
           "it was a real logout — scan it and you're back. Your tasks, history and backups "
           "are never touched either way."))
E.append(callout("If you find yourself re-scanning every few days, the session isn't "
                 "crashing — it's being logged out, and the usual causes are the phone going "
                 "offline, the bot's number being open in WhatsApp Web/Desktop on another "
                 "device, or the machine running low on memory. Keep the phone online and the "
                 "number off other WhatsApp Web sessions."))

E.append(P("Troubleshooting — the restart cookbook", "h2"))
E.append(P("All commands run in Terminal, from the folder TaskWA is installed in "
           "(the one containing <font face='Mono'>docker-compose.yml</font> and "
           "<font face='Mono'>data/</font>). Nothing here loses data — the "
           "database, backups and the WhatsApp pairing all live in "
           "<font face='Mono'>data/</font> on your disk and survive every "
           "restart below."))
E.append(table(["Situation", "Do this"],
    [["WhatsApp gateway stuck (FAILED / stuck QR / no messages)",
      Paragraph("On the Health page click <b>Restart gateway session</b> first — it "
                "restarts the session with no QR and fixes most cases. Still stuck: "
                "<font face='Mono'>docker compose restart waha</font> — wait a "
                "minute, check Health. Stubborn: <font face='Mono'>docker compose "
                "up -d --force-recreate waha</font> (pairing survives; a QR "
                "afterwards just means it was a real logout — re-scan it).",
                S["tcell"])],
     ["App misbehaving / dashboard not loading",
      Paragraph("<font face='Mono'>docker compose restart app</font>", S["tcell"])],
     ["Restart everything cleanly",
      Paragraph("<font face='Mono'>docker compose down</font> then "
                "<font face='Mono'>docker compose up -d</font>", S["tcell"])],
     ["Docker itself is wedged",
      Paragraph("Quit Docker Desktop from the whale menu, reopen it, wait for "
                "the steady whale, then <font face='Mono'>docker compose up "
                "-d</font>.", S["tcell"])],
     ["'docker: command not found'",
      Paragraph("Docker's CLI links are broken (typical after switching "
                "container engines). Docker Desktop → Settings → Advanced → "
                "toggle the CLI tools to <b>User</b>, Apply, back to "
                "<b>System</b>, Apply &amp; Restart (enter your password). "
                "Never run two container engines at once.", S["tcell"])],
     ["Nothing starts after a reboot",
      Paragraph("The autostart isn't armed. From the install folder run "
                "<font face='Mono'>./scripts/autostart-macos.sh</font> "
                "(Windows: <font face='Mono'>autostart-windows.ps1</font>, "
                "Linux: <font face='Mono'>sudo ./scripts/autostart-linux.sh"
                "</font>). Also set: Docker Desktop → 'Start when you sign "
                "in', automatic login, and on a Mac <font face='Mono'>sudo "
                "pmset -a autorestart 1</font> for power cuts. Verify: check "
                "<font face='Mono'>launchctl list | grep taskwa</font>, log at "
                "<font face='Mono'>/tmp/taskwa-autostart.log</font>. Full "
                "chain: docs/UNATTENDED.md.", S["tcell"])],
     ["What actually happened?",
      Paragraph("<font face='Mono'>docker compose logs app --since 30m</font> — "
                "every message, drop reason and error is logged. The Health "
                "page's message log shows every outbound send and why any "
                "were blocked.", S["tcell"])]],
    [4.0*cm, FW-4.0*cm]))
E.append(P("The acid test after any repair: reboot the machine, touch nothing, "
           "wait three minutes, open the Health page — it should say "
           "<b>WORKING</b> on its own."))

E.append(P("Routine care", "h2"))
for b in [
 "<b>Backups are automatic</b> — nightly database snapshots, 14 kept, in the backups folder. To restore: stop the app, copy a snapshot over data/tasks.db, start again.",
 "<b>Exports</b> — tasks.csv and audit.csv from the Tasks page, any time.",
 "<b>Forgotten password</b> — 'Forgot password' on the login page sends a 6-digit code to your WhatsApp. If WhatsApp itself is down: docker compose exec app python -m app.cli reset-password",
 "<b>Upgrades</b> — see docs/UPGRADE.md; in short: git pull, docker compose up -d --build. Data survives.",
 "<b>Survive restarts automatically</b> — run the one-command autostart installer for your OS (scripts/autostart-macos.sh, autostart-windows.ps1, sudo autostart-linux.sh): at every login/boot it starts Docker, waits for the engine, and brings TaskWA up. Full four-link chain (auto power-on, auto-login, Docker, containers) in docs/UNATTENDED.md.",
 "<b>Keep the machine awake</b> — a sleeping laptop sends no digests. Digests missed by under 6 hours send on wake; missed nudges are skipped on purpose.",
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
