# Go Time: Deploying Your Server

*Listen close, chummer. This isn't one of those sterile docs that reads
like a corp manual. This is the actual sequence of moves you're going to
make when you sit down in front of that HP box. Miss a step and things
get messy. Follow it clean and you'll have a fully operational rig in
about 20 minutes.*

---

## Before You Touch the Server

You need three things sorted on the HP **before** you go headless:

1. **Plug the HP into your router with an ethernet cable.** A server
   running DNS for your network on Wi-Fi is asking for trouble. If
   Wi-Fi hiccups, every device loses DNS (and effectively internet).
   Do this first — the setup script auto-detects the IP, and you want
   it to grab the wired one.

2. **Install SSH so you can reach it from your laptop.** Plug in a
   keyboard and monitor, log in directly, and run:
   ```bash
   sudo apt install openssh-server
   ```
   (Ubuntu/Debian) or `sudo dnf install openssh-server` (Fedora).

3. **Disable Wi-Fi on the HP.** You want it using only the wired
   connection from now on:
   ```bash
   sudo nmcli radio wifi off
   ```

Now find the HP's **wired** IP address:
```bash
hostname -I | awk '{print $1}'
```

Write this down — you'll type it a lot. We'll call it `THE_IP` from
here on.

From your **laptop**, verify SSH works:
```bash
ssh your-username@THE_IP
```

If that doesn't work, fix it before moving on. Nothing else matters
until you have a shell on that box.

---

## The Rundown (10 Steps)

### 1. Install git and clone the repo

SSH into the HP, then:
```bash
sudo apt install git
git clone https://github.com/Warchafter/home-server.git
cd home-server
```

*If the clone asks for credentials, the repo is set to private. Either
make it public on GitHub (Settings > Danger Zone > Change visibility)
or create a [Personal Access Token](https://github.com/settings/tokens)
and paste it as the password. Since there are no secrets in the repo
(they're all in `.env` which is gitignored), public is fine.*

*Your entire server config lives in this repo. The HP box just runs it.
That means if the box ever dies, you clone this onto a new machine and
you're back in business. That's the play.*

---

### 2. Run the bootstrap script

```bash
bash scripts/setup.sh
```

This does the heavy lifting — installs Docker, installs Tailscale, fixes
the Ubuntu DNS conflict so AdGuard can use port 53, detects your IP, and
creates your `.env` config file.

It'll ask you to confirm a few things along the way. Say yes to
everything unless you have a reason not to.

**Expect this to take 3-5 minutes** depending on your internet speed.

---

### 3. Log out and back in

Docker needs you in the `docker` group. The script added you, but Linux
won't recognize it until you start a fresh session.

```bash
exit
```

SSH back in:
```bash
ssh your-username@THE_IP
cd home-server
```

Quick sanity check — this should work **without** `sudo`:
```bash
docker ps
```

If it says "permission denied," you didn't log out and back in. Do that.

---

### 4. Check your .env

```bash
nano .env
```

The script auto-filled most of this. Just verify:
- **SERVER_IP** — matches the HP's wired LAN IP
- **TZ** — your timezone looks right

Don't touch anything else. Save and exit (`Ctrl+X`, then `Y`, then `Enter`).

---

### 5. Fire it up

The Docker services share a network called `proxy`. Create it first,
then start everything:

```bash
docker network create proxy
docker compose up -d
```

Docker pulls the images (first run downloads ~400MB total) and starts
all five containers. **This will take a couple minutes on first run.**

Check that everything came up:
```bash
docker compose ps
```

You want to see all five services with `running` status. If something
says `restarting`, check its logs:
```bash
docker compose logs adguard
```

---

### 6. Complete the AdGuard setup wizard

*This is the one step people forget, and then they wonder why DNS isn't
working. Don't be that person.*

Open a browser on your laptop and go to:
```
http://THE_IP:3000
```

The wizard will ask you to:
1. **Set the admin web interface** to listen on port `80` and listen
   address `All interfaces` — **leave the defaults, just hit Next**
2. **Set the DNS server** to listen on port `53` — **again, defaults are fine**
3. **Create an admin username and password** — pick something you'll
   remember, you'll need it for the dashboard widget later
4. **Choose upstream DNS** — use `1.1.1.1` (Cloudflare) or `8.8.8.8`
   (Google), either works

Finish the wizard. You'll land on the AdGuard dashboard.

**Right after the wizard**, add your credentials to `.env` so the
Homepage dashboard can show AdGuard stats:

```bash
nano .env
```

Uncomment and fill in:
```
ADGUARD_USER=whatever-you-picked
ADGUARD_PASS=whatever-you-picked
```

Then recreate Homepage to pick up the new env vars:
```bash
docker compose up -d homepage
```

*Note: `docker compose restart` does NOT reload environment variables.
Always use `docker compose up -d` when you change `.env`.*

---

### 7. Verify everything works

Open these URLs in your browser. All from your laptop, all using the
HP's IP:

| What | URL | What you should see |
|------|-----|---------------------|
| Dashboard | `http://THE_IP` | Homepage with service cards and AdGuard stats |
| Uptime Kuma | `http://THE_IP:8090` | Monitoring setup page |
| AdGuard | `http://THE_IP:8091` | AdGuard admin panel (login required) |

If the dashboard loads with AdGuard stats showing, your whole stack is
running. That's the confirmation.

---

### 8. Point your devices to AdGuard

You have two options for making AdGuard your DNS:

**Option A: Router-wide** — every device on your network uses AdGuard.
Simple, but affects everyone (roommates, family).

**Option B: Per-device** — only your devices use AdGuard. Safer when
you share a network.

Pick one. If you're not sure, go with Option B — you can always switch
to router-wide later.

#### Option A: Router-wide DNS

1. Log into your router's admin page (usually `192.168.0.1` or `192.168.1.1`)
2. Find **DHCP Server** settings (sometimes under LAN or Network)
3. Set **Primary DNS** to `THE_IP`
4. Set **Secondary DNS** to `1.1.1.1` (fallback if the HP is ever off)
5. Save

Devices pick this up as their DHCP leases renew (check your router's
lease time — could be up to 2 hours). To force it immediately on any
device, toggle its Wi-Fi off and back on.

#### Option B: Per-device DNS

**Linux laptop:**
```bash
# Find your Wi-Fi connection name
nmcli con show --active

# Set DNS (replace YOUR_WIFI_NAME with the name from above)
nmcli con mod "YOUR_WIFI_NAME" ipv4.dns "THE_IP"
nmcli con mod "YOUR_WIFI_NAME" ipv4.ignore-auto-dns yes
nmcli con down "YOUR_WIFI_NAME" && nmcli con up "YOUR_WIFI_NAME"
```

To undo:
```bash
nmcli con mod "YOUR_WIFI_NAME" ipv4.dns ""
nmcli con mod "YOUR_WIFI_NAME" ipv4.ignore-auto-dns no
nmcli con down "YOUR_WIFI_NAME" && nmcli con up "YOUR_WIFI_NAME"
```

**Windows 11:**
1. Settings > Network & internet > Wi-Fi > your network
2. Click **Edit** next to DNS server assignment
3. Switch to **Manual**, toggle **IPv4** on
4. Preferred DNS: `THE_IP`, Alternate DNS: `1.1.1.1`
5. Save

**Android (Pixel, etc.):**
1. Settings > Network & internet > Internet
2. Tap the gear next to your Wi-Fi network, then the pencil icon
3. Advanced options > IP settings > **Static**
4. Fill in: your phone's current IP, Gateway `192.168.0.1`,
   Prefix length `24`, DNS 1 `THE_IP`, DNS 2 `1.1.1.1`
5. Save

**IMPORTANT for Android:** Check Settings > Network & internet >
**Private DNS**. If it's set to "Automatic," it overrides your
per-network DNS with Google's DNS-over-TLS. Set it to **Off** for
your local AdGuard to work.

*Note: Static IP on Android means your phone always requests that
specific IP. If you go to a different Wi-Fi network (work, coffee
shop), switch back to DHCP or you won't get internet.*

**Verify it's working** (on any device):
```bash
nslookup google.com THE_IP
```
If you get an answer, AdGuard is handling your DNS. Check the AdGuard
dashboard — you should see your device's IP in the "Top clients" list.

---

### 9. Set a static IP for the HP

Your router hands out IPs that can change. If the HP's IP changes,
everything breaks — DNS stops, the dashboard moves, your bookmarks are
wrong.

In your router's admin page, find **DHCP reservation** (sometimes called
"static lease" or "address reservation"). Add an entry:
- **MAC address** — find the HP's ethernet MAC with:
  ```bash
  ip addr show | grep -B1 "THE_IP"
  ```
  The `link/ether` line above your IP is the MAC (e.g., `04:0e:3c:89:58:80`).
  If your router has a "View Connected Devices" button, that's even easier.
- **IP:** whatever `THE_IP` is right now

This tells your router: "Always give this machine the same IP."

---

### 10. (Optional) Set up Tailscale for remote access

If you want to reach your server from outside your house — phone on
cellular, laptop at a coffee shop — Tailscale makes it dead simple.

The setup script already installed it. Just activate it:

```bash
sudo tailscale up --advertise-routes=192.168.0.0/24
```

Replace `192.168.0.0/24` with your actual subnet (check with
`ip route | grep -v default | head -1`). Then:

1. Go to [tailscale.com/admin](https://login.tailscale.com/admin/machines)
2. Find your server, click `...` > Edit route settings
3. Approve the subnet route

Install Tailscale on your phone/laptop and you can hit `http://THE_IP`
from anywhere in the world. No port forwarding, no exposed services.

*The full Tailscale walkthrough is in `docs/tailscale-setup.md` if you
need it.*

---

## After It's Running

Your server is now live. Here's what you should know going forward:

**Check on things:**
```bash
docker compose ps        # are all containers running?
docker compose logs -f   # stream all logs (Ctrl+C to stop)
```

**If you change config files on your laptop and push to GitHub:**
```bash
# On the HP:
cd ~/home-server
git pull
docker compose up -d
```

**The one command you never run:**
```
docker compose down -v    <-- THIS DESTROYS ALL YOUR DATA
```

The `-v` wipes every volume — AdGuard config, Uptime Kuma monitors,
Caddy certificates. `docker compose down` (without `-v`) is fine. It
stops containers but keeps data.

---

## What DNS Blocking Does (and Doesn't Do)

DNS-level ad blocking kills requests to known ad/tracking domains before
they ever reach your browser. It works across every device and every app
without installing anything per-app.

**What it blocks well:**
- Third-party trackers and analytics (Google Analytics, Facebook Pixel, etc.)
- Ad network domains (doubleclick, adsrvr, etc.)
- Malware and phishing domains
- Telemetry (Mozilla, Microsoft, etc.)

**What it can't block:**
- Ads served from the same domain as content (YouTube ads come from
  `googlevideo.com` — block that and you block all YouTube)
- In-app ads served from first-party domains
- Ads baked directly into webpage HTML

For more aggressive browser ad blocking, pair DNS with **uBlock Origin**
(browser extension). DNS catches what extensions miss (system-wide, all
apps), extensions catch what DNS can't (same-origin ads). Together they
cover most of it.

---

## If Something Goes Wrong

**Container won't start / keeps restarting:**
```bash
docker compose logs THE_SERVICE_NAME
```
The answer is almost always in the logs.

**Port 53 conflict (AdGuard can't start):**
The setup script should have fixed this, but if not:
```bash
sudo ss -tulnp | grep ':53 '
```
If `systemd-resolved` is holding port 53, the fix is in the setup script
comments or just re-run `bash scripts/setup.sh`.

**Can't reach anything from browser:**
- Is the HP on? (`ssh` into it)
- Are containers running? (`docker compose ps`)
- Are you using the right IP?
- Is your laptop on the same network as the HP?

**Homepage shows "API Error" for AdGuard:**
- Did you add `ADGUARD_USER` and `ADGUARD_PASS` to `.env`?
- Did you run `docker compose up -d homepage` (not `restart`)?
- Do the credentials match what you set in the AdGuard wizard?

---

*That's the whole play, nova. You've got a reverse proxy, network-wide ad
blocking, uptime monitoring, and a clean dashboard. Not bad for 20 minutes
of work. Now go set a static IP on that router before DHCP shuffles your
addresses and you're chasing ghosts.*
