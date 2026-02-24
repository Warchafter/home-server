# Tailscale Setup

Tailscale lets you securely access your home server from anywhere — phone, laptop, coffee shop — without opening any ports on your router.

## 1. Create an Account

Go to [tailscale.com](https://tailscale.com) and sign up (free for up to 100 devices).

## 2. Install on the Server

The `setup.sh` script installs Tailscale automatically. If you need to do it manually:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

## 3. Connect and Advertise Your LAN

```bash
# Replace 192.168.1.0/24 with your actual LAN subnet.
# Find it with: ip route | grep -v default | head -1
sudo tailscale up --advertise-routes=192.168.1.0/24
```

This does two things:
- Connects your server to your Tailscale network
- Tells Tailscale "I can route traffic to the 192.168.1.x network"

## 4. Approve the Subnet Route

Tailscale requires you to manually approve subnet routes for security:

1. Open [Tailscale Admin Console](https://login.tailscale.com/admin/machines)
2. Find your server in the list
3. Click the `...` menu > **Edit route settings**
4. Enable the subnet route you advertised

## 5. Install on Your Devices

Install Tailscale on your phone/laptop:
- [iOS](https://apps.apple.com/app/tailscale/id1470499037)
- [Android](https://play.google.com/store/apps/details?id=com.tailscale.ipn)
- [macOS/Windows/Linux](https://tailscale.com/download)

Once connected, you can access your server using either:
- Its Tailscale IP (shown in the admin console, usually `100.x.x.x`)
- Its LAN IP (e.g., `192.168.1.100`) if you approved subnet routes

## 6. Optional: Enable MagicDNS

In the admin console, enable **MagicDNS** to access your server by name (e.g., `hp-server`) instead of IP.

## Troubleshooting

**"Cannot reach server via Tailscale"**
- Check that Tailscale is running: `tailscale status`
- Verify subnet route is approved in admin console
- Ensure IP forwarding is enabled: `cat /proc/sys/net/ipv4/ip_forward` (should be `1`)
- If not: `echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.d/99-tailscale.conf && sudo sysctl -p /etc/sysctl.d/99-tailscale.conf`

**"Connected but can't reach other LAN devices"**
- Subnet routes need to be approved (step 4)
- Your firewall may be blocking forwarded traffic: `sudo ufw allow in on tailscale0`
