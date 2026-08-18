---
name: connect-workstation
description: Connect to a deployed Isaac Workstation via noVNC, KasmVNC, NoMachine, NICE DCV, xrdp, Sunshine+Moonlight, or SSH.
---

# connect-workstation <!-- omit in toc -->

- [Pick the right method](#pick-the-right-method)
- [noVNC (standard browser desktop)](#novnc-standard-browser-desktop)
- [KasmVNC (WebRTC browser desktop with native clipboard)](#kasmvnc-webrtc-browser-desktop-with-native-clipboard)
- [NoMachine (live 3D viewport)](#nomachine-live-3d-viewport)
- [NICE DCV (enterprise GPU streaming)](#nice-dcv-enterprise-gpu-streaming)
- [xrdp (Microsoft Remote Desktop)](#xrdp-microsoft-remote-desktop)
- [Sunshine + Moonlight (ultra-low latency 3D)](#sunshine--moonlight-ultra-low-latency-3d)
- [Parsec (interactive streaming)](#parsec-interactive-streaming)
- [SSH (shell)](#ssh-shell)

You need a deployed, running workstation (see `../deploy-workstation/SKILL.md`; resume a stopped one with
`./start <name>`). All connection info is also saved in `state/<name>/info.txt`.

## Pick the right method

| Want to... | Use |
|---|---|
| Click around desktop, launch apps in browser | noVNC (standard) or KasmVNC |
| In-browser desktop with native copy-paste (`Ctrl+V`) | KasmVNC |
| Watch the live Isaac Sim / Isaac Lab 3D viewport (rendered robots) | NoMachine, NICE DCV, Sunshine, or Parsec |
| Connect from standard Windows/Mac Remote Desktop app | xrdp |
| Ultra-low latency 60/120 FPS robotics teleoperation | Sunshine + Moonlight |
| Run commands, read logs, launch a demo headlessly | SSH |

The 3D viewport is the key distinction: Omniverse Kit renders via a Vulkan surface that legacy VNC does **not**
capture. Use **NoMachine**, **NICE DCV**, **Sunshine + Moonlight**, or **Parsec** for live 3D graphics.

## noVNC (standard browser desktop)

```sh
./novnc <name>
```

This prints a URL of the form `http://<ip>:6080/vnc.html?host=<ip>&port=6080&password=<vnc_password>&resize=scale`.

## KasmVNC (WebRTC browser desktop with native clipboard)

When deployed with `--remote-desktop standard,kasmvnc` (or `kasmvnc`):
- Open `https://<ip>:8444` in any modern web browser.
- Enter your VNC password from `state/<name>/meta.json`.
- Supports direct native clipboard synchronization via Async Web Clipboard API.

## NoMachine (live 3D viewport)

1. Install the NoMachine client from https://downloads.nomachine.com/ and launch it.
2. Add a connection to **Host** = the workstation public IP (port 4000).
3. Use key-based auth with the private key at `state/<name>/key.pem`.
4. Connect and log in as the SSH user (default `ubuntu`).

## NICE DCV (enterprise GPU streaming)

When deployed with `--remote-desktop standard,dcv` (or `dcv`):
- **Web Browser**: Navigate to `https://<ip>:8443`
- **Native Client**: Connect to `<ip>:8443`
- **Credentials**: User `ubuntu`, system password from `state/<name>/meta.json`.

## xrdp (Microsoft Remote Desktop)

When deployed with `--remote-desktop standard,xrdp` (or `xrdp`):
- Open **Remote Desktop Connection** (Windows) or **Microsoft Remote Desktop** (macOS/iOS).
- Connect to `<ip>:3389`.
- Logs into the active GPU console session (`DISPLAY=:0`).

## Sunshine + Moonlight (ultra-low latency 3D)

When deployed with `--remote-desktop standard,sunshine` (or `sunshine`):
1. Install and open the Moonlight client (https://moonlight-stream.org/).
2. Add the host `<ip>`.
3. Open `https://<ip>:47990` in your browser and enter the 4-digit pairing PIN displayed by Moonlight.

## Parsec (interactive streaming)

When deployed with `--remote-desktop standard,parsec`:
- Connect directly to the workstation host name in your Parsec client.

## SSH (shell)

```sh
./ssh <name>
```

Or directly with the saved key:

```sh
ssh -i state/<name>/key.pem -o StrictHostKeyChecking=no ubuntu@<ip>
```

Use SSH to read logs, launch a demo's `~/.local/share/isaac-automator-demos/<demo>.sh` script, or record
viewport video headlessly. Set `DISPLAY=:0` when launching GUI apps so they render on the workstation desktop.
