# -*- coding: utf-8 -*-
"""TaskWA Installation Guide with drawn step illustrations + 1-page cheat sheet."""
from dg_common import *

import os
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "TaskWA-Installation-Guide.pdf")
CHEAT = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "TaskWA-Command-Card.pdf")


def cover(cv):
    cv.setFillColor(ORANGE); cv.rect(0, 0, 1.1*cm, PAGE_H, stroke=0, fill=1)
    cv.setFillColor(ORANGE); cv.setFont("Serif-Bold", 46)
    cv.drawString(ML+0.4*cm, PAGE_H-6.2*cm, "TaskWA")
    cv.setFillColor(INK); cv.setFont("Serif-Bold", 22)
    cv.drawString(ML+0.4*cm, PAGE_H-7.5*cm, "Installation Guide")
    cv.setFillColor(CHAR); cv.setFont("Serif", 11.5)
    cv.drawString(ML+0.4*cm, PAGE_H-8.6*cm,
                  "From an empty computer to a working WhatsApp task")
    cv.drawString(ML+0.4*cm, PAGE_H-9.15*cm,
                  "manager in about thirty minutes.")
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 9)
    cv.drawString(ML+0.4*cm, PAGE_H-10.2*cm,
                  "macOS (Apple Silicon & Intel) · Windows · Linux    ·    Version 1.6")
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 7.8)
    cv.drawString(ML+0.4*cm, 1.9*cm,
                  "Illustrations are drawn representations of the real screens; "
                  "exact appearance varies slightly by version.")


doc = make_doc(OUT, "TaskWA Installation Guide · v1.6", "Installation Guide", cover)
E = []
start_body(E)

# ---- what you need ----
E += section("1", "Before you begin — what you need")
E.append(table(["Item", "Details"],
    [["A computer that stays on", "Mac (Apple Silicon or Intel), Windows 10/11, or Linux. "
      "4 GB RAM is plenty. This machine is the server: reminders only go out while it is "
      "awake and Docker is running."],
     ["A WhatsApp number for the bot", "Either a dedicated SIM (safest) or your own "
      "personal number (supported via Personal-number mode — understand the ban-risk "
      "trade-off in the User Manual first)."],
     ["A phone with that number's WhatsApp", "Needed once, to scan a QR code."],
     ["30 minutes", "Most of it is Docker downloading things."]],
    [4.4*cm, FW-4.4*cm]))
E.append(callout("Every command in this guide is also in <b>INSTALL.txt</b> in the "
                 "project folder — open it side-by-side and copy-paste each block in order."))

# ---- docker ----
E += section("2", "Install Docker Desktop")
E.append(P("Docker runs TaskWA's three components in isolated containers — it is the only "
           "software you install yourself."))
E.append(P("<b>macOS:</b> download from <font face='Mono'>docker.com/products/docker-desktop</font> "
           "— choose <b>Apple Silicon</b> for M1/M2/M3/M4 Macs, <b>Intel</b> otherwise. Open "
           "the .dmg, drag Docker into Applications, then launch it once and approve the "
           "system prompts. <b>Windows:</b> the installer enables WSL2; if it complains about "
           "virtualization, enable it in BIOS/UEFI (usually 'SVM' or 'VT-x'). <b>Linux:</b> "
           "<font face='Mono'>curl -fsSL https://get.docker.com | sh</font>"))

def il_docker(cv, w, h):
    win_frame(cv, 0, 4, w*0.56, h-8, "Docker Desktop")
    cv.setFillColor(colors.HexColor("#5BB960")); cv.circle(16, h-34, 4, stroke=0, fill=1)
    cv.setFillColor(INK); cv.setFont("Helvetica-Bold", 8.5)
    cv.drawString(26, h-37, "Docker Desktop is running")
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 7.5)
    cv.drawString(26, h-50, "Engine started - ready to run containers")
    for i, (name, st_) in enumerate((("taskwa-app-1", "Running"),
                                     ("taskwa-waha-1", "Running"))):
        yy = h-72-i*16
        cv.setFillColor(PAPER2); cv.rect(14, yy-4, w*0.56-28, 14, stroke=0, fill=1)
        cv.setFillColor(INK); cv.setFont("Mono", 7); cv.drawString(18, yy, name)
        cv.setFillColor(colors.HexColor("#3A7D44")); cv.setFont("Helvetica-Bold", 7)
        cv.drawRightString(w*0.56-18, yy, st_)
    cv.setFillColor(ORANGE_D); cv.setFont("Serif-Bold", 9)
    cv.drawString(w*0.60, h-30, "Checklist after first launch:")
    cv.setFillColor(CHAR); cv.setFont("Helvetica", 8)
    for i, t in enumerate(["Whale icon steady in the menu bar / tray",
                           "Settings > General >",
                           "   'Start Docker Desktop when you sign in'  ON",
                           "Terminal: docker --version prints a version"]):
        cv.drawString(w*0.60, h-46-i*13, ("✓  " if i in (0, 3) else "    ") + t)

E.append(Illu(il_docker, 118))
E.append(Paragraph("Fig. 1 — Docker Desktop running, with both TaskWA containers up "
                   "(as it will look after step 4).", S["cap"]))

# ---- get code / env ----
E += section("3", "Get TaskWA and set your secrets")
E.append(P("Open Terminal (macOS: Cmd-Space, type Terminal · Windows: PowerShell) and run:"))
E.append(codebox([
 "git clone https://github.com/sudhakar-kadavasal/taskwa.git   # or unzip the release",
 "cd taskwa",
]))
E.append(Spacer(1, 4))
E.append(P("Then paste this whole block — it creates your <font face='Mono'>.env</font>, "
           "generates all three secrets automatically, and detects your CPU to enable the "
           "ARM gateway image when needed (Apple Silicon Macs, Raspberry Pi). On Windows, "
           "run it in <b>Git Bash</b> (installed with Git), not PowerShell:"))
E.append(codebox([
 "cp .env.example .env",
 "",
 "for key in WEBHOOK_SECRET APP_SECRET WAHA_API_KEY; do",
 "  val=$(openssl rand -hex 24)",
 "  if [ \"$(uname)\" = \"Darwin\" ]; then sed -i '' \"s|^$key=.*|$key=$val|\" .env",
 "  else sed -i \"s|^$key=.*|$key=$val|\" .env; fi",
 "done",
 "",
 "case \"$(uname -m)\" in arm64|aarch64)",
 "  if [ \"$(uname)\" = \"Darwin\" ]; then sed -i '' 's|^# *WAHA_TAG=arm|WAHA_TAG=arm|' .env",
 "  else sed -i 's|^# *WAHA_TAG=arm|WAHA_TAG=arm|' .env; fi ;;",
 "esac",
 "",
 "grep -q change-me .env && echo \"!! secrets NOT set\" || echo \"secrets OK\"",
]))
E.append(callout("The last line must print <b>secrets OK</b>. If it doesn't (or you can't "
                 "use Git Bash), edit <font face='Mono'>.env</font> by hand: run "
                 "<font face='Mono'>openssl rand -hex 24</font> three times, paste one "
                 "result into each secret, and on Apple Silicon / Raspberry Pi uncomment "
                 "<font face='Mono'>WAHA_TAG=arm</font> — without it Docker reports "
                 "'no matching manifest for linux/arm64'."))

# ---- start ----
E += section("4", "Start it")
E.append(P("This step needs Docker <b>running</b> — you installed it in step 2, right? "
           "If not, get it now from <font face='Mono'>docker.com/products/docker-desktop</font>, "
           "launch it once, wait for the whale icon, then come back."))
E.append(codebox(["docker compose up -d"]))
E.append(Spacer(1, 4))

def il_term(cv, w, h):
    term_frame(cv, 0, 4, w, h-8, [
        "$ docker compose up -d",
        "[+] Running 2/2",
        " ✔ Container taskwa-waha-1   Started",
        " ✔ Container taskwa-app-1    Started",
        "$ docker compose ps",
        "NAME            STATUS",
        "taskwa-app-1    Up 15 seconds",
        "taskwa-waha-1   Up 16 seconds",
    ])
E.append(Illu(il_term, 108))
E.append(Paragraph("Fig. 2 — First start. The initial run downloads ~1 GB; give it a few "
                   "minutes. Both containers must show 'Up'.", S["cap"]))

# ---- wizard ----
E += section("5", "The setup wizard")
E.append(P("Open <font face='Mono-Bold'>http://localhost:3000</font> in your browser. "
           "TaskWA starts in <b>dry-run mode</b> — nothing is sent to anyone until you "
           "switch it off, so you cannot accidentally spam your team while setting up."))

def il_wizard(cv, w, h):
    browser_frame(cv, 0, 4, w, h-8, "localhost:3000/setup")
    cv.setFillColor(INK); cv.setFont("Serif-Bold", 11)
    cv.drawString(16, h-40, "Setup wizard")
    steps = ["1  Admin password", "2  Pair WhatsApp  [SCAN_QR_CODE]",
             "3  Timezone & daily send time", "4  Team members",
             "5  Test & finish"]
    for i, t in enumerate(steps):
        yy = h-58-i*15
        cv.setStrokeColor(ORANGE); cv.setLineWidth(2)
        cv.line(16, yy-3, 16, yy+8)
        cv.setFillColor(CHAR); cv.setFont("Helvetica", 8.5)
        cv.drawString(24, yy, t)
E.append(Illu(il_wizard, 145))
E.append(Paragraph("Fig. 3 — The five wizard steps, in order.", S["cap"]))
E.append(Spacer(1, 4))
for t in [
 "<b>Step 1 — Admin password.</b> Eight characters or more. This protects the dashboard.",
 "<b>Step 2 — Pair WhatsApp</b> (next section — the only step involving a phone).",
 "<b>Step 3 — Timezone and send time.</b> IANA name (Asia/Dubai, Asia/Kolkata, Europe/London) "
 "and the daily digest time, 24-hour clock. Several times? Comma-separate: 08:00, 17:30.",
 "<b>Step 4 — Team members.</b> Name + WhatsApp number, digits only with country code "
 "(9715xxxxxxxx). Add yourself first, as admin.",
 "<b>Step 5 — Test.</b> Send the test message; in dry-run it appears in the Health page log "
 "rather than on your phone — that is correct. Click Finish.",
 "<b>Using your own personal number as the bot?</b> After the wizard, open Settings and "
 "tick <b>Personal number mode</b> — your digest then arrives in WhatsApp's 'Message "
 "Yourself' chat, and the bot stays silent on everything that isn't a command.",
]:
    E.append(P("•  " + t, "bullet"))

# ---- QR ----
E += section("6", "Pairing WhatsApp — the QR scan")

def il_qr(cv, w, h):
    browser_frame(cv, 0, 4, w*0.52, h-8, "localhost:3000/setup")
    cv.setFillColor(INK); cv.setFont("Serif-Bold", 9.5)
    cv.drawString(14, h-38, "2 - Pair WhatsApp")
    qr_block(cv, 40, 24, 88)
    cv.setFillColor(MUTED); cv.setFont("Helvetica", 6.8)
    cv.drawString(14, 14, "Scan, wait 10 s, refresh")
    phone_frame(cv, w*0.60, 10, w*0.17, h-20, "WhatsApp")
    cv.setFillColor(CHAR); cv.setFont("Helvetica", 7.4)
    x = w*0.60 + w*0.17 + 12
    lines = ["On the bot number's phone:", "", "WhatsApp > Settings >",
             "Linked devices >", "Link a device", "",
             "Point the camera at the QR.", "",
             "Status becomes WORKING", "within ~30 seconds."]
    for i, t in enumerate(lines):
        cv.drawString(x, h-32-i*12.5, t)
E.append(Illu(il_qr, 150))
E.append(Paragraph("Fig. 4 — Browser shows the QR; the bot number's phone scans it.",
                   S["cap"]))
E.append(Spacer(1, 3))
E.append(P("If the QR does not appear: wait 60 seconds (the gateway boots a full browser "
           "engine internally — slower on Apple Silicon's first run), click <i>Start / "
           "restart session</i>, refresh. The status label above the QR tells you the "
           "state; you want it to end at <b>WORKING</b>."))

# ---- groups + golive ----
E += section("7", "Groups, members, first test, go live")
for t in [
 "<b>Register groups.</b> Add the bot's number to each WhatsApp group you want covered. "
 "Dashboard → Groups → <b>Detect my groups</b> → Register next to each. Unregistered "
 "groups are ignored entirely.",
 "<b>Import members from a group.</b> Members → <b>Import from group</b> → pick a "
 "registered group: every participant appears with name and number pre-filled. Tick, "
 "adjust names, Import. (Participants whose numbers WhatsApp hides need to be saved as "
 "a contact, or make the bot's number a group admin, then re-detect.)",
 "<b>Personal number?</b> Settings → tick <b>Personal number mode</b> → Save. Your own "
 "digest will arrive in WhatsApp's 'Message Yourself' chat.",
 "<b>Dry-run rehearsal.</b> Health → <b>Run digests now</b> → read the message log. "
 "What you see there is exactly what would have been sent.",
 "<b>Go live.</b> Settings → untick Dry-run → Save. Health → Run digests now — this time "
 "the messages land on phones.",
 "<b>Prove the loop.</b> From your phone: /mytasks → create a test task with /add → reply "
 "1 done → watch for the thumbs-up and the dashboard updating.",
]:
    E.append(P("•  " + t, "bullet"))

# ---- unattended ----
E += section("8", "Keep it alive — fully unattended")
E.append(P("Reminders only go out while the machine is on, Docker is running, and the "
           "containers are up. After a reboot or power cut that chain has four links; "
           "the scripts below repair the one Docker's own restart policies miss "
           "(containers that were stopped when Docker last quit). One command, from the "
           "install folder:"))
E.append(codebox([
 "# macOS - LaunchAgent at every login (also starts Docker itself):",
 "./scripts/autostart-macos.sh",
 "",
 "# Windows - Scheduled Task at logon (PowerShell):",
 "powershell -ExecutionPolicy Bypass -File scripts\\autostart-windows.ps1",
 "",
 "# Linux / Raspberry Pi - systemd service, no login needed at all:",
 "sudo ./scripts/autostart-linux.sh",
]))
E.append(Spacer(1, 4))
E.append(P("Each script waits up to five minutes for the Docker engine, then runs "
           "<font face='Mono'>docker compose up -d</font> (idempotent — if everything is "
           "already running it does nothing). Add <font face='Mono'>--uninstall</font> "
           "(or <font face='Mono'>-Uninstall</font>) to remove."))
E.append(P("Complete the chain once: <b>auto power-on</b> after a power cut (macOS: "
           "<font face='Mono'>sudo pmset -a autorestart 1</font>; PCs: 'Restore on AC "
           "power' in BIOS), and <b>automatic login</b> (macOS: System Settings → Users "
           "&amp; Groups; Windows: netplwiz). With FileVault/BitLocker a password is still "
           "needed at cold boot — accept that; don't disable disk encryption. Verify the "
           "whole chain: reboot, touch nothing, wait three minutes, open the Health page — "
           "it should say WORKING. Details: <b>docs/UNATTENDED.md</b>."))
E.append(callout("What the app itself already handles: task digests missed by under six "
                 "hours are sent on startup; missed broadcasts are deliberately skipped "
                 "(a scheduled 'good morning' should not arrive mid-afternoon); the "
                 "WhatsApp pairing survives restarts."))

# ---- troubleshoot ----
E += section("9", "If something goes wrong")
E.append(table(["Symptom", "Fix"],
    [["docker: command not found", "Docker Desktop isn't installed or was never launched. "
      "Launch it, wait for the whale, open a NEW terminal window."],
     ["no matching manifest for linux/arm64", "Apple Silicon / Raspberry Pi: add "
      "WAHA_TAG=arm to .env, then docker compose up -d"],
     ["QR never appears / session FAILED", "Wait 60 s → Start/restart session → refresh. "
      "Persisting: docker compose up -d --force-recreate waha (session store survives; "
      "worst case re-scan the QR)."],
     ["Banner: session UNREACHABLE right after start", "Normal for the first minute while "
      "the gateway boots. Refresh the Health page."],
     ["Replies do nothing", "Is the sender registered with the exact number they message "
      "from? Is the group registered? Check docker compose logs app — every message and "
      "every drop reason is logged."],
     ["Locked out of dashboard", "'Forgot password' sends a code to the admin's WhatsApp. "
      "Gateway down too: docker compose exec app python -m app.cli reset-password"]],
    [FW*0.38, FW*0.62]))
E.append(Spacer(1, 6))
E.append(P("<b>The restart cookbook</b> — from the install folder; none of these "
           "lose data (database, backups and the WhatsApp pairing live in "
           "<font face='Mono'>data/</font> and survive):"))
E.append(codebox([
 "docker compose restart waha        # gateway stuck / QR problems",
 "docker compose restart app         # dashboard misbehaving",
 "docker compose down && docker compose up -d    # full clean restart",
 "docker compose logs app --since 30m            # what actually happened",
 "",
 "# Docker itself wedged: quit Docker Desktop (whale menu), reopen,",
 "# wait for the steady whale, then:  docker compose up -d",
]))
E.append(Spacer(1, 4))
E.append(P("<b>Check the autostart is armed</b> (it is what brings everything "
           "back after reboots and power cuts): macOS "
           "<font face='Mono'>launchctl list | grep taskwa</font> should print a "
           "line — if not, re-run <font face='Mono'>./scripts/autostart-macos.sh"
           "</font> (log: <font face='Mono'>/tmp/taskwa-autostart.log</font>). "
           "Also confirm Docker Desktop's 'Start when you sign in' is ON, "
           "automatic login is enabled, and on a Mac run <font face='Mono'>sudo "
           "pmset -a autorestart 1</font> once. 'docker: command not found' "
           "after switching container engines: Docker Desktop → Settings → "
           "Advanced → toggle CLI tools User → System (password prompt). "
           "Never run two container engines at once."))
E.append(Spacer(1, 4))
E.append(P("Full operational reference: <b>docs/TROUBLESHOOTING.md</b>, <b>docs/UPGRADE.md</b>, "
           "<b>docs/BACKUP.md</b>, <b>docs/UNATTENDED.md</b> and the User Manual in this folder."))

doc.build(E)
print("OK install")

# ================= command card (1 page) =================
def cheat_cover(cv):
    pass

cdoc = make_doc(CHEAT, "TaskWA Command Card", "Command Card", cheat_cover)


def card_page(cv, doc_):
    cv.saveState()
    cv.setFillColor(PAPER); cv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    cv.setFillColor(ORANGE); cv.rect(0, PAGE_H-2.5*cm, PAGE_W, 2.5*cm, stroke=0, fill=1)
    cv.setFillColor(CREAM); cv.setFont("Serif-Bold", 24)
    cv.drawString(ML, PAGE_H-1.75*cm, "TaskWA — Command Card")
    cv.setFillColor(colors.HexColor("#CBE4D6")); cv.setFont("Helvetica", 9.5)
    cv.drawRightString(PAGE_W-MR, PAGE_H-1.7*cm, "pin me in the group")
    cv.restoreState()


cdoc.pageTemplates = []          # card is single-page: no cover sheet
cdoc.addPageTemplates([PageTemplate(id="Card",
    frames=[Frame(ML, MB, FW, PAGE_H-3.4*cm-MB)], onPage=card_page)])
C = []

C.append(Spacer(1, 3))


def big_cmd(cmd, desc):
    t = Table([[Paragraph(f"<font face='Mono-Bold' size=9.6>{cmd}</font>",
                          st("bc", alignment=TA_LEFT, spaceAfter=0, leading=12.2)),
                Paragraph(desc, st("bd", fontSize=8.3, leading=10.6,
                                   alignment=TA_LEFT, spaceAfter=0))]],
              colWidths=[FW*0.40, FW*0.60])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), SAND),
        ("BACKGROUND", (1, 0), (1, -1), CREAM),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ORANGE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return [t, Spacer(1, 3)]


def band(txt):
    """Small section rule above a block of commands."""
    return [Spacer(1, 2),
            Paragraph(f"<b>{txt}</b>",
                      st("band", fontSize=8.6, leading=11, alignment=TA_LEFT,
                         textColor=ORANGE_D, spaceAfter=2, spaceBefore=0)),
            Spacer(1, 1)]


C += band("ADMIN — works only when you DM the bot directly")
for cmd, desc in [
 ("/nudge 07:30 tue @Ravi.Shankar<br/>#\"Group 1\" What is the status?<br/>"
  "/nudges", "<b>Nudger</b> — a plain message the bot sends for you, on a "
  "schedule. Time first (required — <b>07:30 · 7:30 · 730 · 0730 · 7.30 · "
  "7:30am · 730pm · 7am</b> all work), then days (mon,wed or 'daily' or omit = "
  "every day), then who (@members / #groups), then the message — sent word for "
  "word. Reply Y to confirm. <b>/nudges</b> lists them all, numbered; then "
  "<b>/nudge 3 08:15 thu</b> reschedules, <b>/nudge off 3</b> · <b>on 3</b> "
  "pauses/resumes, <b>/nudge delete 3</b> removes it."),
 ("/adduser 971501234567 Ravi Shankar<br/>/rename @Ravi Ravi Shankar<br/>"
  "/members",
  "Register a teammate from your phone — check the number in the Y/N prompt, a "
  "typo would register a stranger. Always joins as a member; promoting to admin "
  "stays on the dashboard. <b>/rename</b> changes the name the team sees (in "
  "group announcements and digests) — two people can never share a name. "
  "<b>/members</b> lists everyone with their roles."),
]:
    C += big_cmd(cmd, desc)

C += band("EVERYONE — the task commands")
for cmd, desc in [
 ("/add Fix pump @Ravi #group fri !high", "New task for Ravi, due Friday, high "
  "priority; #group also posts + announces it in that group. Reply Y to confirm "
  "— Ravi is then asked to accept it."),
 ("/mytasks", "Your open tasks, any time."),
 ("/list", "Every open task you're allowed to see."),
 ("/myadd", "Open tasks you created for others — with status and blocks."),
 ("/help", "The full command list (admins DM'ing the bot also get the admin set)."),
 # --- names and groups with spaces ---
 ("@Ravi.Shankar<br/>@\"Ravi Shankar\"<br/>#Group.1<br/>#\"Group 1\"",
  "A name or a group with a space in it: <b>dot it, or quote it</b> — curly "
  "quotes from your phone are fine. Names and groups follow the same rule. "
  "@Ravi or #group on their own are fine when they match only one person / one "
  "group; if two match, the bot asks instead of guessing."),
 # --- status replies ---
 ("1 done", "Task 1 finished. You'll get a thumbs-up."),
 ("1 in progress", "You've started task 1."),
 ("1 block <i>reason</i>", "You're stuck — say why. The admin is alerted at once."),
 ("1 block waiting on @Ravi.Shankar", "Hand the block to Ravi — he's asked to "
  "release it when his part is done."),
 ("1 unblock", "A block waits on YOU? This releases it and hands the task back to "
  "its owner."),
 ("1 reopen", "Undo a mistaken 'done'."),
 ("1 cancel <i>reason</i>", "Cancel a task YOU created (or you're admin). "
  "The assignee is told it's off their list."),
 ("done", "No number needed if you have just one task — or swipe-reply on the task's message."),
 ("Y  /  N", "Got a 'New task from …'? Y accepts, N sends it back to its creator. "
  "Silence for 30 min = accepted."),
]:
    C += big_cmd(cmd, desc)

C.append(Spacer(1, 3))
C.append(callout("Dates for /add: <b>today · tomorrow · mon…sun · 25/07</b>   —   "
                 "Priorities: <b>!high · !low</b>   —   Only you (or an admin) can "
                 "close your tasks."))
cdoc.build(C)
print("OK card")
