---
name: jarvis-cloud-setup
description: Set up Jarvis on a Google Cloud e2-micro server from the owner's Windows laptop (Session 1 of docs/Jarvis-Session-1.pdf). Use when the user asks to set up, install, deploy, or check the Jarvis cloud server.
---

# Jarvis cloud setup (Session 1)

You are setting up Jarvis on a low-cost Google Cloud server for the owner, from their
laptop. Follow these phases in order. Before each phase, say in one line what you are
about to do. After each phase, confirm the checkpoint before moving on. If anything
fails, stop, show the error, and explain it plainly. Don't improvise around billing
or security.

## Hard rules

- **Never ask for, accept, read, print or log secrets.** That covers the Claude API key,
  the Telegram bot token, Twilio tokens, ngrok tokens, and the server's `.env` file.
  If the user pastes one into the chat, tell them to revoke it and make a new one.
  The owner types secrets only into `python -m jarvis.configure`, in their own
  terminal window, never in this chat.
- **Never `cat`, `grep` or otherwise display `~/jarvis/.env` or `data/hud_token`.**
- **Never enter payment details or create billing accounts.** The owner does that in
  the browser.
- **Free-tier settings are fixed:** zone `us-central1-a` (or `us-east1-b` /
  `us-west1-b`), machine `e2-micro`, disk `pd-standard` 30 GB, Ubuntu 24.04 LTS.
  Don't change them to make something work. Stop and ask instead.
- Run one command at a time and read its output before the next.
- **Windows:** use PowerShell syntax unless Git Bash is the shell. gcloud on Windows
  uses PuTTY for `gcloud compute ssh`; pass `--quiet` so it doesn't stop at prompts.

## Phase 0: Preconditions (ask the owner, don't check secrets)

Confirm in one short message:
1. They finished **Part 1** of the PDF: a new Claude API key and a Telegram bot token,
   saved in their own notes. Don't ask to see them.
2. They have a Google Cloud account with billing set up (signed up at
   console.cloud.google.com and added a card).

If not, point them to Part 1 / Part 2 step A of `docs/Jarvis-Session-1.pdf` and wait.

## Phase 1: gcloud CLI

1. Check `gcloud --version`.
2. If it's missing on Windows: `winget install --id Google.CloudSDK -e`. Then tell the
   owner to close and reopen Claude Code so the new PATH is picked up, and stop here.
3. Ask the owner to sign in by typing this in Claude Code themselves:
   `! gcloud auth login`
   It opens their browser. Wait for them to say it's done.
4. Verify with `gcloud auth list`.

## Phase 2: Project, billing, budget

1. `gcloud projects list`. If there's a suitable project, ask which one to use.
   Otherwise create one: `gcloud projects create jarvis-<6 random lowercase letters/digits> --name="Jarvis"`.
2. `gcloud config set project <PROJECT_ID>`
3. Billing: `gcloud billing accounts list`. If there's exactly one open account, link it:
   `gcloud billing projects link <PROJECT_ID> --billing-account=<ACCOUNT_ID>`.
   If there are none, the owner must add billing in the console first. Stop.
4. `gcloud services enable compute.googleapis.com billingbudgets.googleapis.com` (takes a minute or two)
5. Budget alert ($5, emails at 50/90/100%):
   `gcloud billing budgets create --billing-account=<ACCOUNT_ID> --display-name="Jarvis" --budget-amount=5USD --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0`
   If this command fails, don't retry variations. Ask the owner to create the budget
   in the console (Billing > Budgets & alerts) and continue.

Checkpoint: the project is set, billing is linked, and the budget exists.

## Phase 3: The server

1. If `gcloud compute instances list --filter="name=jarvis"` already shows it, skip to step 3.
2. Create it, with exactly these settings:
   ```
   gcloud compute instances create jarvis --zone=us-central1-a --machine-type=e2-micro --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud --boot-disk-size=30GB --boot-disk-type=pd-standard
   ```
3. Verify the cost-relevant settings:
   `gcloud compute disks describe jarvis --zone=us-central1-a --format="value(type.basename(),sizeGb)"`
   It must print `pd-standard` and `30`.
   `gcloud compute instances describe jarvis --zone=us-central1-a --format="value(machineType.basename(),status)"`
   It must print `e2-micro` and `RUNNING`.
   If either is wrong, stop and tell the owner. Offer to delete the server (only with
   their yes) so it doesn't cost money.

Checkpoint: `e2-micro`, `pd-standard`, `RUNNING`.

## Phase 4: Install Jarvis on the server

1. The first SSH connection generates keys. Run:
   `gcloud compute ssh jarvis --zone=us-central1-a --quiet --command="echo connected"`
   It may take a minute while the keys are added. Retry once if it times out.
2. Clone (or update) and install:
   `gcloud compute ssh jarvis --zone=us-central1-a --quiet --command="git clone https://github.com/cmdevsarnia/jarvis.git ~/jarvis 2>/dev/null || git -C ~/jarvis pull; cd ~/jarvis && bash deploy/setup-server.sh"`
   This takes 2-4 minutes.
3. **If the clone fails with an authentication error** (the repository is private),
   don't ask for a GitHub token. Copy the code from this laptop instead (run from the
   repository root):
   ```
   git archive --format=tar.gz -o jarvis-src.tgz HEAD
   gcloud compute scp jarvis-src.tgz jarvis:~/ --zone=us-central1-a --quiet
   gcloud compute ssh jarvis --zone=us-central1-a --quiet --command="mkdir -p ~/jarvis && tar -xzf ~/jarvis-src.tgz -C ~/jarvis && rm ~/jarvis-src.tgz && cd ~/jarvis && bash deploy/setup-server.sh"
   ```
   Then delete the local `jarvis-src.tgz`. Tell the owner updates will work the same
   way later (no `git pull` on the server).

Checkpoint: the output ends with "Next: enter your keys with ...".

## Phase 5: The owner enters their keys (you don't see them)

Tell the owner to open a **separate PowerShell window** (not this chat) and run:
```
gcloud compute ssh jarvis --zone=us-central1-a
```
then inside it:
```
cd jarvis
.venv/bin/python -m jarvis.configure
sudo systemctl restart jarvis
exit
```
Explain the answers: paste the Claude key (nothing shows while pasting, that's
normal), model **1** (Sonnet 5.5), their name, paste the Telegram token, leave the
chat id blank, **N** to phone calls. Wait for them to say done.

## Phase 6: Verify and connect Telegram

1. Check the service (the logs are safe: Jarvis keeps tokens out of them):
   `gcloud compute ssh jarvis --zone=us-central1-a --quiet --command="systemctl is-active jarvis; journalctl -u jarvis -n 25 --no-pager"`
   Expect `active` and a "Telegram bot polling" line. If you see "API key was
   rejected" or a crash, explain it and send the owner back to Phase 5.
2. Ask the owner to message their bot "hello" on Telegram. It replies with their chat
   id. A chat id is not a secret, so they can tell you the number.
3. Save it and restart (replace `<ID>`; digits and an optional leading minus only, so
   check that before running):
   `gcloud compute ssh jarvis --zone=us-central1-a --quiet --command="cd ~/jarvis && .venv/bin/python -c \"from dotenv import set_key; set_key('.env','TELEGRAM_OWNER_CHAT_ID','<ID>',quote_mode='never')\" && sudo systemctl restart jarvis && sleep 3 && systemctl is-active jarvis"`
4. Ask the owner to text the bot: "What's the server's CPU load?"

Checkpoint: Jarvis replies on Telegram. Session 1 is done.

## Finish

Summarize what was created: project id, server `jarvis` in `us-central1-a`, budget
alert. Say what it costs (about $3.65/month for the public IP address plus Claude
usage) and how to pause it to stop most costs:
`gcloud compute instances stop jarvis --zone=us-central1-a` (start it again with `start`).
A stopped server still pays for its disk and IP, so suggest `delete` only if they're
done with Jarvis, and only after confirming with them.
Next steps: phone calls (Session 2, `docs/Jarvis-Setup-Guide.pdf` Add-on), the phone
web app, email alerts.
