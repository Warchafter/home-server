#!/usr/bin/env python3
"""
alert-check.py — host-side watchdog that does NOT depend on Prometheus.

Prometheus is the first casualty of a full disk (its WAL stops writing and its
head block empties), so the thing that watches the disk has to live outside it.
This runs from cron on the host and checks:

  * root filesystem usage — measured as the space available to NON-root
    processes, which is what the containers actually see (ext4 reserves ~5%
    for root, so `df` can read 97% while every container gets ENOSPC)
  * containers that are not running, report unhealthy, or have sat in
    "health: starting" for longer than STUCK_MINUTES — the restart-loop
    signature autoheal produces when a container crashes at startup

Sends one message per NEW problem, a reminder every REMIND_HOURS while it
persists, and a "resolved" message when it clears. Delivery is a Discord
webhook and/or a Telegram bot — both outbound-only, so they work from a
LAN-only server with no public domain.

Configure in .env (next to compose.yaml):
    ALERT_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
    ALERT_TELEGRAM_BOT_TOKEN=123456789:ABC...
    ALERT_TELEGRAM_CHAT_ID=123456789
    ALERT_DISK_THRESHOLD=85            # optional, percent

Install ON THE SERVER (as your normal user — it is in the docker group):
    crontab -e
    */10 * * * * /usr/bin/python3 /home/wachacha/home-server/scripts/alert-check.py >> /var/tmp/alert-check.log 2>&1

Manual use:
    python3 scripts/alert-check.py --print    # show findings, send nothing, touch no state
    python3 scripts/alert-check.py --test     # send a test message to every configured channel
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = Path("/var/tmp/home-server-alert-state.json")
MOUNTS = ["/"]
STUCK_MINUTES = 5
REMIND_HOURS = 24
DEFAULT_DISK_THRESHOLD = 85

_UP_RE = re.compile(r"^Up (?:(About a|About an|Less than a|\d+) )?(second|minute|hour|day|week|month|year)s?", re.I)
_UNIT_MIN = {"second": 1 / 60, "minute": 1, "hour": 60, "day": 1440, "week": 10080, "month": 43200, "year": 525600}


def load_env() -> dict:
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("ALERT_")})
    return env


# ---------------------------------------------------------------------------
# Checks — each returns {key: human message}
# ---------------------------------------------------------------------------

def check_disk(threshold: float) -> dict:
    problems = {}
    for mp in MOUNTS:
        try:
            u = shutil.disk_usage(mp)
        except OSError:
            continue
        # u.free is f_bavail: what non-root processes can still write
        effective_pct = (u.total - u.free) / u.total * 100
        if effective_pct >= threshold:
            problems[f"disk:{mp}"] = (
                f"disk {mp} is {effective_pct:.0f}% full for services "
                f"({u.free / 1e9:.1f} GB left of {u.total / 1e9:.0f} GB)"
            )
    return problems


def up_minutes(status: str):
    m = _UP_RE.match(status or "")
    if not m:
        return None
    qty, unit = m.group(1), m.group(2).lower()
    if qty in (None, "About a", "About an"):
        n = 1.0
    elif qty == "Less than a":
        n = 0.0
    else:
        n = float(qty)
    return n * _UNIT_MIN[unit]


def check_containers() -> dict:
    docker = shutil.which("docker") or "/usr/bin/docker"
    try:
        out = subprocess.run(
            [docker, "ps", "-a", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as e:
        return {"docker": f"cannot talk to docker: {e}"}
    problems = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        name, state, status = c.get("Names", "?"), c.get("State", "?"), c.get("Status", "")
        if state != "running":
            problems[f"container:{name}"] = f"{name} is {state} ({status})"
        elif "unhealthy" in status:
            problems[f"container:{name}"] = f"{name} is unhealthy ({status})"
        elif "health: starting" in status:
            mins = up_minutes(status)
            if mins is not None and mins >= STUCK_MINUTES:
                problems[f"container:{name}"] = (
                    f"{name} stuck in health=starting for {mins:.0f} min — crash/restart loop? ({status})"
                )
    return problems


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def send(env: dict, text: str) -> bool:
    sent = False
    hook = env.get("ALERT_DISCORD_WEBHOOK")
    if hook:
        req = urllib.request.Request(
            hook,
            data=json.dumps({"content": text[:1900]}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "home-server-alert-check/1"},
        )
        try:
            urllib.request.urlopen(req, timeout=15).read()
            sent = True
        except Exception as e:  # noqa: BLE001
            print(f"discord send failed: {e}", file=sys.stderr)
    token, chat = env.get("ALERT_TELEGRAM_BOT_TOKEN"), env.get("ALERT_TELEGRAM_CHAT_ID")
    if token and chat:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15).read()
            sent = True
        except Exception as e:  # noqa: BLE001
            print(f"telegram send failed: {e}", file=sys.stderr)
    if not hook and not (token and chat):
        print("no alert channel configured (ALERT_DISCORD_WEBHOOK / ALERT_TELEGRAM_*); message was:\n" + text)
    return sent


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state))
    except OSError as e:
        print(f"cannot write state file {STATE_FILE}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", action="store_true", help="print findings, send nothing, do not touch state")
    ap.add_argument("--test", action="store_true", help="send a test message and exit")
    args = ap.parse_args()

    env = load_env()
    host = socket.gethostname()
    if args.test:
        ok = send(env, f"✅ alert-check test from {host} — delivery works")
        return 0 if ok else 1

    threshold = float(env.get("ALERT_DISK_THRESHOLD", DEFAULT_DISK_THRESHOLD))
    problems = {}
    problems.update(check_disk(threshold))
    problems.update(check_containers())

    if args.print:
        print("\n".join(problems.values()) if problems else "no problems")
        return 0

    now = time.time()
    state = load_state()
    new = [k for k in problems if k not in state]
    reminders = [k for k in problems if k in state and now - state[k]["last_sent"] >= REMIND_HOURS * 3600]
    resolved = [k for k in state if k not in problems]

    lines = []
    lines += [f"🔴 {host}: {problems[k]}" for k in new]
    lines += [f"🟠 {host}: still — {problems[k]}" for k in reminders]
    lines += [f"✅ {host}: resolved — {state[k]['msg']}" for k in resolved]

    for k in new:
        state[k] = {"first": now, "last_sent": now, "msg": problems[k]}
    for k in reminders:
        state[k]["last_sent"] = now
    for k in resolved:
        del state[k]

    if lines:
        send(env, "\n".join(lines))
    save_state(state)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} {len(problems)} active problem(s); sent {len(lines)} line(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
