"""Builds docs/Jarvis-Setup-Guide.pdf"""
import sys
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
                                Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle)

OUT = sys.argv[1]
INK = colors.HexColor("#14202b")
ACCENT = colors.HexColor("#0b7fab")
MUTED = colors.HexColor("#5b6b78")
CODE_BG = colors.HexColor("#eef3f6")
WARN_BG = colors.HexColor("#fff4e0"); WARN_LINE = colors.HexColor("#e09a2b")
TIP_BG = colors.HexColor("#e6f5fb"); TIP_LINE = ACCENT
RULE = colors.HexColor("#c9d6df")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5, leading=15, textColor=INK, spaceAfter=6)
small = ParagraphStyle("small", parent=body, fontSize=9, leading=12.5, textColor=MUTED)
h1 = ParagraphStyle("h1", parent=body, keepWithNext=1, fontName="Helvetica-Bold", fontSize=19, leading=24, textColor=ACCENT, spaceBefore=4, spaceAfter=4)
h2 = ParagraphStyle("h2", parent=body, keepWithNext=1, fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=INK, spaceBefore=12, spaceAfter=4)
title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=30, leading=36, textColor=ACCENT, spaceAfter=2)
subtitle = ParagraphStyle("subtitle", parent=body, fontSize=13, leading=18, textColor=MUTED, spaceAfter=14)
cell = ParagraphStyle("cell", parent=body, fontSize=9.5, leading=13, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
codestyle = ParagraphStyle("code", fontName="Courier", fontSize=9.3, leading=12.5, textColor=INK)

story = []
P = lambda t, s=body: story.append(Paragraph(t, s))
H1 = lambda t: story.extend([Paragraph(t, h1), _rule()])
H2 = lambda t: story.append(Paragraph(t, h2))


def keep_from(i):
    block = story[i:]
    del story[i:]
    story.append(KeepTogether(block))


def _rule():
    t = Table([[""]], colWidths=[6.9 * inch], rowHeights=[2])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 1, RULE)]))
    return t


def code(text):
    pre = Preformatted(text.strip("\n"), codestyle)
    t = Table([[pre]], colWidths=[6.9 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([t, Spacer(1, 7)])


def box(label, text, bg, line):
    content = [Paragraph(f"<b>{label}</b>", ParagraphStyle("bl", parent=body, textColor=line, spaceAfter=2))]
    for para in text if isinstance(text, list) else [text]:
        content.append(Paragraph(para, ParagraphStyle("bt", parent=body, spaceAfter=3)))
    t = Table([[content]], colWidths=[6.9 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, line),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.extend([t, Spacer(1, 9)])


warn = lambda text, label="Important": box(label, text, WARN_BG, WARN_LINE)
tip = lambda text, label="Tip": box(label, text, TIP_BG, TIP_LINE)


def steps(items, start=1):
    flow = ListFlowable([ListItem(Paragraph(i, body), leftIndent=18, value=n)
                         for n, i in enumerate(items, start)],
                        bulletType="1", start=start, bulletFontName="Helvetica-Bold",
                        bulletColor=ACCENT, leftIndent=18, bulletFontSize=10.5)
    story.extend([flow, Spacer(1, 4)])


def bullets(items):
    flow = ListFlowable([ListItem(Paragraph(i, body), leftIndent=14) for i in items],
                        bulletType="bullet", start="•", leftIndent=14, bulletColor=ACCENT)
    story.extend([flow, Spacer(1, 4)])


def table(rows, widths, header=True):
    data = [[Paragraph(c, cellb if (header and r == 0) or c_i == 0 else cell) for c_i, c in enumerate(row)]
            for r, row in enumerate(rows)]
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1 if header else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.5, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), CODE_BG))
    t.setStyle(TableStyle(style))
    story.extend([t, Spacer(1, 10)])


# ======================================================================= cover
P("J.A.R.V.I.S.", title)
P("Setup guide: Claude-powered assistant with phone chat, phone calls, and a desktop HUD", subtitle)

warn([
    "<b>Revoke the API key you pasted into the chat earlier.</b> Anything pasted into a chat is stored "
    "and should be treated as public. Go to <b>platform.claude.com &gt; API Keys</b>, delete it, and create a new one.",
    "From now on, keys only ever go into Jarvis's settings tool (Step 3). Never into chats, emails, or GitHub.",
], "Do this first")

H2("How it fits together")
P("Jarvis is a small program that runs all the time on a computer you control. It sends what you say to "
  "Claude, runs tools (web search, texting you, calling you), and answers. You reach it three ways:")
table([
    ["Channel", "What it is", "Needs"],
    ["Telegram", "Text Jarvis from your phone, any time", "Free Telegram bot"],
    ["Phone call", "Jarvis rings your cell and you talk to it", "Twilio number + a tunnel (ngrok)"],
    ["Desktop HUD", "The movie-style screen with voice, at your PC", "A Windows PC with Chrome or Edge"],
], [1.2, 3.3, 2.4])

H2("Pick your path")
table([
    ["", "Path A: Cloud server", "Path B: Home PC"],
    ["When", "Now, set up from a laptop", "When you have a PC to leave on"],
    ["You get", "Telegram + phone calls, always on", "Everything, including the HUD with voice and PC control"],
    ["Hosting cost", "About $0-4 per month", "$0 (it uses your PC)"],
    ["Hardest part", "Clicking through Google's cloud console", "Nothing; double-click an installer"],
], [1.3, 2.8, 2.8])
tip("Start with <b>Path A, Telegram only</b>. It's the cheapest way to have a working Jarvis today. Add phone "
    "calls once you're happy, and move to Path B when you have a PC. Your settings carry over.",
    "Recommendation")

_k = len(story)
H2("What it costs (approximate, check current prices)")
table([
    ["Item", "Price", "Notes"],
    ["Claude API", "Pay per use", "Sonnet 5.5: $2 / $10 per million input / output tokens. Opus 5.5: $4 / $20. "
     "A short back-and-forth on Sonnet is typically well under a cent. Prepaid credit; you set a monthly limit."],
    ["Telegram", "Free", ""],
    ["Cloud server", "$0-4 / month", "Google Cloud's e2-micro VM is free, but Google bills its public IP "
     "(about $0.005/hour, roughly $3.65/month). Oracle's Always Free tier is $0, but it stops servers that sit idle for a week, which Jarvis usually does."],
    ["Twilio (calls)", "$1.15 / month + per minute", "Local US number $1.15/month; outbound US calls about "
     "$0.013-0.014/minute, plus speech-recognition fees. New accounts get trial credit."],
    ["ngrok (tunnel)", "Free", "Free plan includes one fixed web address, which is all Jarvis needs."],
], [1.3, 1.4, 4.2])
P("<b>Realistic budget for light personal use: about $5-10 per month</b> on Sonnet with occasional calls. "
  "This is an estimate. Your spend limit in Step 1 guarantees it can't run away.", small)
keep_from(_k)

# =================================================================== accounts
H1("Step 1: Claude API key")
P("This is how Jarvis pays for Claude. It is separate from any claude.ai subscription.")
steps([
    "Open <b>platform.claude.com</b> and sign in (or sign up).",
    "Go to <b>Billing</b> and add a small amount of prepaid credit (for example $5-10).",
    "Go to <b>Limits</b> and set a <b>monthly spend limit</b> you're comfortable with. This is your safety net.",
    "Go to <b>API Keys &gt; Create Key</b>, name it <b>jarvis</b>, and copy it. It starts with "
    "<font name='Courier'>sk-ant-api</font>. Keep it in a locked notes app or password manager until Step 3.",
])
H2("Choosing a model (you'll pick it in Step 3)")
table([
    ["Model", "Best for", "Cost"],
    ["Sonnet 5.5", "Everyday assistant use. <b>Recommended for low cost.</b>", "About half of Opus"],
    ["Opus 5.5", "The smartest answers and trickier multi-step tasks", "Highest"],
    ["Haiku 5.5", "The cheapest option; no web search", "Lowest"],
], [1.3, 4.0, 1.6])

_k = len(story)
H1("Step 2: Telegram bot (5 minutes, on your phone)")
steps([
    "Install <b>Telegram</b> and create an account.",
    "Search for <b>@BotFather</b> (it has a blue check mark) and open the chat.",
    "Send <font name='Courier'>/newbot</font>. Give it a name (e.g. <i>Jarvis</i>) and a username that ends in "
    "<i>bot</i> (e.g. <i>tony_jarvis_bot</i>).",
    "BotFather replies with a <b>token</b> like <font name='Courier'>123456789:AAF...</font>. Copy it and keep it with your API key.",
])
P("You'll get your <b>chat id</b> later: the first time you message your bot, Jarvis replies with it.", small)
keep_from(_k)

# ======================================================================= path A
H1("Path A: Run Jarvis on a cloud server")
P("These steps use Google Cloud from a web browser. A <b>Windows laptop</b> is ideal: you install nothing "
  "on it, because Google's <b>SSH</b> button opens a terminal in a browser window. (From a phone, turn on "
  "<b>Desktop site</b> in the browser menu.) Google's screens change from time to time, so button names "
  "may differ slightly.")

H2("A1. Create the account and a budget alert")
steps([
    "Go to <b>console.cloud.google.com</b> and sign up. A card is required for verification. New accounts "
    "usually get free trial credit, which covers the first months.",
    "Open <b>Billing &gt; Budgets &amp; alerts &gt; Create budget</b>. Set it to <b>$5</b> so you're "
    "emailed if anything costs more than expected.",
])

H2("A2. Create the server")
steps([
    "Go to <b>Compute Engine &gt; VM instances</b> (click <b>Enable</b> if asked) and press <b>Create instance</b>.",
    "<b>Name:</b> jarvis. <b>Region:</b> us-central1, us-west1 or us-east1 (only these are in the free tier).",
    "<b>Machine type:</b> <b>e2-micro</b>.",
    "<b>Boot disk &gt; Change:</b> Ubuntu 24.04 LTS, disk type <b>Standard persistent disk</b>, size 30 GB. "
    "The default disk type is <i>not</i> free, so change it.",
    "Leave everything else as is and press <b>Create</b>. Wait for the green check mark.",
])

H2("A3. Install Jarvis")
P("Press the <b>SSH</b> button next to your VM and click <b>Authorize</b>. A terminal window opens. Paste "
  "these lines one at a time (Ctrl+V, or right-click &gt; Paste), pressing Enter after each:")
code("""
git clone https://github.com/cmdevsarnia/jarvis.git
cd jarvis
bash deploy/setup-server.sh
""")
tip("If the repository is private, GitHub asks for a username and password. Use your GitHub username, and for "
    "the password a <b>personal access token</b> (GitHub &gt; Settings &gt; Developer settings &gt; "
    "Personal access tokens &gt; Fine-grained, read-only access to this one repository).",
    "Private repository?")

H2("A4. Enter your settings")
code(".venv/bin/python -m jarvis.configure")
P("It asks one question at a time: paste your Claude key, pick model <b>1</b> (Sonnet), enter what "
  "Jarvis should call you, and paste your Telegram token. Leave the chat id blank for now, and answer "
  "<b>N</b> to phone calls. Your keys are hidden while you type and stored readable only by you. Then start Jarvis:")
code("sudo systemctl restart jarvis")

H2("A5. Connect Telegram")
steps([
    "In Telegram, open your bot and send <i>hello</i>. It replies with <b>Your chat id is ...</b>",
    "Back in the SSH window run <font name='Courier'>.venv/bin/python -m jarvis.configure</font> again. "
    "Press Enter to keep each existing value and paste the chat id when asked.",
    "Run <font name='Courier'>sudo systemctl restart jarvis</font>.",
    "Message the bot: <i>Jarvis, what's the server's CPU load?</i> You should get a reply in a few seconds.",
])
P("Jarvis now starts automatically whenever the server boots. You can close the SSH window. "
  "Useful commands: <font name='Courier'>systemctl status jarvis</font> (is it running?), "
  "<font name='Courier'>journalctl -u jarvis -n 50</font> (last 50 log lines).", small)

H2("Free alternative: Oracle Cloud")
P("Oracle's <b>Always Free</b> tier includes a VM <i>and</i> its public IP at $0, but free accounts have "
  "servers <b>stopped if they stay idle for 7 days</b>. Jarvis is idle most of the time, so you'd need to "
  "upgrade to Pay As You Go (free resources stay free, but you can be billed for anything beyond them). "
  "If you try it: create an Ubuntu instance (shape VM.Standard.E2.1.Micro), connect with its <b>Cloud Shell</b>, "
  "then follow A3-A5 exactly as written.")

# ======================================================================= path B
story.append(PageBreak())
H1("Path B: Run Jarvis on a Windows PC")
steps([
    "Install <b>Python 3.12 or newer</b> from python.org. On the first installer screen, tick "
    "<b>Add python.exe to PATH</b>.",
    "Get the code: on the GitHub page for the repository, press <b>Code &gt; Download ZIP</b> and unzip it "
    "to e.g. <font name='Courier'>Documents\\Jarvis</font>.",
    "Double-click <b>start-jarvis.bat</b>. The first run installs everything (a few minutes) and then asks "
    "your settings, the same questions as Path A.",
    "Jarvis opens the HUD in your browser. Use <b>Microsoft Edge</b> for the best voice, and allow the microphone.",
    "Hold <b>Space</b> (or click <b>MIC</b>) and talk. Tick <b>WAKE WORD</b> to just say <i>\"Jarvis, ...\"</i> hands-free.",
    "Connect Telegram as in A5. To change settings later, open a terminal in the folder and run "
    "<font name='Courier'>.venv\\Scripts\\python -m jarvis.configure</font>.",
    "Optional: edit <font name='Courier'>config\\apps.json</font> to list apps Jarvis may open for you.",
])
warn("Only one Jarvis can use a Telegram bot at a time. If you move from the cloud server to your PC, stop the "
     "server's copy first (<font name='Courier'>sudo systemctl disable --now jarvis</font>) or create a second bot.",
     "Running both?")
P("Jarvis only runs while the window is open and the PC is awake. To start it automatically, add "
  "<b>start-jarvis.bat</b> to Windows Task Scheduler with the trigger <i>At log on</i>.", small)

# ======================================================================= calls
H1("Add-on: Phone calls")
P("Jarvis can ring your cell and hold a spoken conversation. Do this after Telegram works.")
H2("C1. Twilio number")
steps([
    "Sign up at <b>twilio.com</b>. During signup, verify your own cell number.",
    "In the Console, <b>Phone Numbers &gt; Buy a number</b>: pick one with <b>Voice</b> capability (about $1.15/month).",
    "From the Console home page, copy your <b>Account SID</b> and <b>Auth Token</b>.",
])
P("On a trial account, Twilio can only call your verified number and plays a short trial message first. "
  "Upgrading removes that.", small)

H2("C2. Tunnel (so Twilio can reach Jarvis)")
steps([
    "Sign up free at <b>ngrok.com</b>. In the dashboard, copy your <b>authtoken</b>, then under <b>Domains</b> "
    "claim your free static domain (looks like <font name='Courier'>something.ngrok-free.app</font>).",
    "<b>Cloud server:</b> in the SSH window run the line below and paste the token and domain when asked. "
    "It keeps the tunnel running permanently.",
])
code("bash deploy/setup-ngrok.sh")
P("<b>Windows PC:</b> download ngrok for Windows, then in a second window run the command shown in your ngrok "
  "dashboard. It looks like <font name='Courier'>ngrok http --url=YOUR-DOMAIN 8000</font>. Keep that window open.", small)

H2("C3. Tell Jarvis and test")
steps([
    "Run the settings tool again and answer <b>y</b> to phone calls. Enter the SID, token, your Twilio number and "
    "your cell (both with + and country code, e.g. <font name='Courier'>+15551234567</font>), and the public URL "
    "<font name='Courier'>https://YOUR-DOMAIN</font>.",
    "Restart Jarvis.",
    "Text your bot: <i>call me</i>. Your phone rings. Talk normally. Say <i>goodbye</i> to hang up.",
])
P("Calling <i>into</i> Jarvis is off by default, because caller ID can be faked. Jarvis only ever calls your number.", small)

# ================================================================== trouble
story.append(PageBreak())
H1("Troubleshooting")
table([
    ["Symptom", "Fix"],
    ["Bot never replies", "Check <font name='Courier'>systemctl status jarvis</font> and the logs. Make sure the "
     "token is right and only one copy of Jarvis is running (logs show <i>409 Conflict</i> otherwise)."],
    ["Bot replies with your chat id every time", "TELEGRAM_OWNER_CHAT_ID isn't set yet. Run the settings tool and restart."],
    ["<i>My API key was rejected</i>", "The Claude key is wrong or revoked. Make a new one and run the settings tool."],
    ["<i>I'm being rate limited</i>, or errors about credit", "Add credit or raise the limit at platform.claude.com."],
    ["<i>Phone calls are not configured</i>", "One of the Twilio settings or PUBLIC_BASE_URL is blank."],
    ["Call connects, then <i>an application error has occurred</i>",
     "Twilio can't reach Jarvis. Check the tunnel is running and PUBLIC_BASE_URL exactly matches the ngrok domain "
     "(https, no trailing slash)."],
    ["Phone doesn't ring on a trial account", "Your cell must be a verified number in Twilio."],
    ["HUD says <i>Access token missing</i>", "Open the exact HUD link printed in the Jarvis window (it includes a token)."],
    ["Microphone does nothing", "Use Chrome or Edge, and allow microphone access when the browser asks."],
], [2.2, 4.7])

H1("Safety checklist")
bullets([
    "The key you pasted in chat is revoked, and a spend limit is set on platform.claude.com.",
    "Keys exist only in Jarvis's settings (.env file), which is never uploaded to GitHub.",
    "TELEGRAM_OWNER_CHAT_ID is set, so Jarvis ignores everyone else.",
    "Inbound calls stay off unless you understand the caller-ID risk.",
    "Jarvis can't run arbitrary commands. Each tool is deliberately narrow, so a stolen phone can't take over your PC.",
    "Calling other people or businesses for you is not built in yet. When it is, it should say it's an AI "
    "and only call numbers you approve. AI-voice calls are regulated in the US.",
])

_k = len(story)
H2("Everyday commands (cloud server)")
table([
    ["What", "Command"],
    ["Is Jarvis running?", "<font name='Courier'>systemctl status jarvis</font>"],
    ["Recent logs", "<font name='Courier'>journalctl -u jarvis -n 50</font>"],
    ["Change settings", "<font name='Courier'>cd ~/jarvis &amp;&amp; .venv/bin/python -m jarvis.configure</font>"],
    ["Restart", "<font name='Courier'>sudo systemctl restart jarvis</font>"],
    ["Update to the latest code", "<font name='Courier'>cd ~/jarvis &amp;&amp; git pull &amp;&amp; sudo systemctl restart jarvis</font>"],
    ["Clear the conversation", "Send <font name='Courier'>/reset</font> to the bot"],
], [2.0, 4.9])
keep_from(_k)


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.8 * inch, 0.5 * inch, "J.A.R.V.I.S. setup guide")
    canvas.drawRightString(7.7 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                        topMargin=0.75 * inch, bottomMargin=0.8 * inch,
                        title="J.A.R.V.I.S. Setup Guide", author="Jarvis project")
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print("wrote", OUT)
