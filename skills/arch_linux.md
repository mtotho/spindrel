---
name: Arch Linux
description: Knowledge on linux commands and users machine. test
--

## Machine Identity
- **Hostname:** totharchy
- **User:** mtoth
- **OS:** Arch Linux (kernel 6.18.13-arch1-1)
- **Hardware:** ASUS PRIME B450M-A II (desktop)
- **IP:** 10.10.100.239/24 (enp7s0)
- **Primary NIC:** enp7s0 (use this for network-aware commands)

## Shell Environment
- **Shell:** `/usr/bin/bash` — do NOT assume zsh syntax
- **Editor:** `nvim` (`vi` and `vim` are aliased to nvim)
- **Terminal multiplexer:** tmux + Alacritty (`TERM=tmux-256color`)
- **Window manager:** Hyprland (Wayland session)
- **Package managers:** `yay` (AUR, preferred) and `pacman` (system)
  - For installs: `yay -S <pkg>` (handles both AUR and official repos)
  - No flatpak, no snap

## Critical Alias Overrides
These aliases change the behavior of common commands — always account for them:

| Typed command | Actual binary | Notes |
|---|---|---|
| `cat` | `bat` | pager output, use `/bin/cat` for raw piping |
| `grep` | `rg` (ripgrep) | rg flags differ from grep |
| `ls` | `ls -aFh --color=always` | color codes may break parsing |
| `rm` | `trash -v` | does NOT delete permanently — use `/bin/rm` for real deletes |
| `vi` / `vim` | `nvim` | |
| `mkdir` | `mkdir -p` | |
| `cp` | `cp -i` | interactive, will prompt on overwrite |
| `mv` | `mv -i` | interactive |
| `ping` | `ping -c 10` | stops after 10 packets |
| `ps` | `ps auxf` | |

**When piping or scripting, prefer full binary paths** (`/bin/cat`, `/usr/bin/grep`, `/bin/rm`) to avoid alias interference.

## Modern CLI Tools Available
- `eza` — modern ls replacement (richer output, git-aware)
- `bat` — cat with syntax highlighting
- `rg` (ripgrep) — fast grep replacement
- `fd` — fast find replacement
- `fzf` — fuzzy finder (interactive selection)
- `zoxide` — smart `cd` with frecency

## Input Remapping (keyd)
- **CapsLock → Escape** (global, via keyd daemon)
- No other remappings active

## Docker Stack (agent-server project)
Running containers on `~/work/agent-server` (or similar):

| Container | Port | Purpose |
|---|---|---|
| agent-server-searxng-1 | 8080 | SearXNG search engine |
| agent-server-playwright-1 | 3000 | Playwright browser automation |
| agent-server-postgres-1 | 5432 | PostgreSQL database |

- Docker socket is active: `/var/run/docker.sock`
- Network bridge `br-66010311d87f` (172.19.0.1/16) is UP — this is the agent-server compose network
- Use `docker ps`, `docker logs <name>`, `docker compose` from the project dir

## Key System Services
**User (systemd --user):**
- `elephant.service` — custom user service (purpose TBD, verify with `systemctl --user status elephant`)
- `mako` — Wayland notification daemon
- `waybar` — status bar
- `hypridle` / `hyprsunset` — idle/blue-light management
- `walker` — app launcher

**System:**
- `docker.service` — container runtime
- `keyd.service` — keyboard remapping
- `iwd.service` — wireless (even though enp7s0 wired is primary)
- `sddm.service` — display manager
- `systemd-networkd` — networking (not NetworkManager)

## Dotfiles / Config Layout
Dotfiles are **symlink-managed** (GNU Stow pattern). Many `~/.config/` entries ending in `@` are symlinks — do not overwrite them directly.

Notable configs:
- `~/.config/nvim` → symlinked
- `~/.config/hypr` → symlinked
- `~/.config/tmux` → symlinked
- `~/.config/waybar` → symlinked
- `~/.config/omarchy/` — Omarchy base config
- `~/.config/opencode` → OpenCode CLI agent config

## Remote Machines (not on this host)
- **Mac Mini M2 Pro (32GB)** — local Ollama/AI server; ollama is NOT installed on totharchy
  - Access via SSH (hostname/IP TBD; ask user or check `~/.ssh/config`)
- **Proxmox host** — VM hypervisor (network-local)
- **TrueNAS** — media/NAS server (network-local)

## Sudo / Privilege
- `sudo` is available; assume password may be required for system-level commands
- Prefer `systemctl --user` for user services before escalating to `sudo systemctl`

## Package Management Patterns
```bash
yay -S <package>          # install (AUR + official)
yay -Rns <package>        # remove with unused deps
yay -Syu                  # full system upgrade
yay -Ss <term>            # search
yay -Qi <package>         # local package info
```

## Common Useful Aliases (agent should know these)
```bash
yayf         # fzf-powered interactive package search + install
docker-clean # prune containers, images, networks, volumes
topcpu       # top 10 CPU-consuming processes
openports    # active inet ports (netstat)
da           # formatted date string
h '<term>'   # search bash history
p '<term>'   # grep running processes
```

## Do NOTs
- **Do not use `rm`** expecting permanent deletion — it calls `trash`. Use `/bin/rm` explicitly when deletion is required.
- **Do not assume zsh** — no zsh installed. Bash-only syntax.
- **Do not use `apt-get`** — Arch uses pacman/yay (the alias exists but is misleading if invoked)
- **Do not pipe through `cat` or `grep`** without considering the bat/rg aliases
- **Do not call `ollama`** locally — it is not installed on totharchy; it runs on the Mac Mini
- **Do not blindly `systemctl restart`** user services without `--user` flag for user-scoped units
- **Do not edit symlinked dotfiles in place** — changes should go through the dotfiles source repo

## Hyprland / Wayland Notes
- Display server: Wayland (no Xorg)
- `WAYLAND_DISPLAY` is set; X11-only tools may fail
- Notifications: `notify-send` routes through `mako`
- Clipboard: use `wl-copy` / `wl-paste` (not xclip/xsel)
- Screenshots: use `hyprshot` or `grimblast` if available
# Machine Identity
- **Hostname:** totharchy
- **User:** mtoth
- **OS:** Arch Linux (kernel 6.18.13-arch1-1)
- **Hardware:** ASUS PRIME B450M-A II (desktop)
- **IP:** 10.10.100.239/24 (enp7s0)
- **Primary NIC:** enp7s0 (use this for network-aware commands)

## Shell Environment
- **Shell:** `/usr/bin/bash` — do NOT assume zsh syntax
- **Editor:** `nvim` (`vi` and `vim` are aliased to nvim)
- **Terminal multiplexer:** tmux + Alacritty (`TERM=tmux-256color`)
- **Window manager:** Hyprland (Wayland session)
- **Package managers:** `yay` (AUR, preferred) and `pacman` (system)
  - For installs: `yay -S <pkg>` (handles both AUR and official repos)
  - No flatpak, no snap

## Critical Alias Overrides
These aliases change the behavior of common commands — always account for them:

| Typed command | Actual binary | Notes |
|---|---|---|
| `cat` | `bat` | pager output, use `/bin/cat` for raw piping |
| `grep` | `rg` (ripgrep) | rg flags differ from grep |
| `ls` | `ls -aFh --color=always` | color codes may break parsing |
| `rm` | `trash -v` | does NOT delete permanently — use `/bin/rm` for real deletes |
| `vi` / `vim` | `nvim` | |
| `mkdir` | `mkdir -p` | |
| `cp` | `cp -i` | interactive, will prompt on overwrite |
| `mv` | `mv -i` | interactive |
| `ping` | `ping -c 10` | stops after 10 packets |
| `ps` | `ps auxf` | |

**When piping or scripting, prefer full binary paths** (`/bin/cat`, `/usr/bin/grep`, `/bin/rm`) to avoid alias interference.

## Modern CLI Tools Available
- `eza` — modern ls replacement (richer output, git-aware)
- `bat` — cat with syntax highlighting
- `rg` (ripgrep) — fast grep replacement
- `fd` — fast find replacement
- `fzf` — fuzzy finder (interactive selection)
- `zoxide` — smart `cd` with frecency

## Input Remapping (keyd)
- **CapsLock → Escape** (global, via keyd daemon)
- No other remappings active

## Docker Stack (agent-server project)
Running containers on `~/work/agent-server` (or similar):

| Container | Port | Purpose |
|---|---|---|
| agent-server-searxng-1 | 8080 | SearXNG search engine |
| agent-server-playwright-1 | 3000 | Playwright browser automation |
| agent-server-postgres-1 | 5432 | PostgreSQL database |

- Docker socket is active: `/var/run/docker.sock`
- Network bridge `br-66010311d87f` (172.19.0.1/16) is UP — this is the agent-server compose network
- Use `docker ps`, `docker logs <name>`, `docker compose` from the project dir

## Key System Services
**User (systemd --user):**
- `elephant.service` — custom user service (purpose TBD, verify with `systemctl --user status elephant`)
- `mako` — Wayland notification daemon
- `waybar` — status bar
- `hypridle` / `hyprsunset` — idle/blue-light management
- `walker` — app launcher

**System:**
- `docker.service` — container runtime
- `keyd.service` — keyboard remapping
- `iwd.service` — wireless (even though enp7s0 wired is primary)
- `sddm.service` — display manager
- `systemd-networkd` — networking (not NetworkManager)

## Dotfiles / Config Layout
Dotfiles are **symlink-managed** (GNU Stow pattern). Many `~/.config/` entries ending in `@` are symlinks — do not overwrite them directly.

Notable configs:
- `~/.config/nvim` → symlinked
- `~/.config/hypr` → symlinked
- `~/.config/tmux` → symlinked
- `~/.config/waybar` → symlinked
- `~/.config/omarchy/` — Omarchy base config
- `~/.config/opencode` → OpenCode CLI agent config

## Remote Machines (not on this host)
- **Mac Mini M2 Pro (32GB)** — local Ollama/AI server; ollama is NOT installed on totharchy
  - Access via SSH (hostname/IP TBD; ask user or check `~/.ssh/config`)
- **Proxmox host** — VM hypervisor (network-local)
- **TrueNAS** — media/NAS server (network-local)

## Sudo / Privilege
- `sudo` is available; assume password may be required for system-level commands
- Prefer `systemctl --user` for user services before escalating to `sudo systemctl`

## Package Management Patterns
```bash
yay -S <package>          # install (AUR + official)
yay -Rns <package>        # remove with unused deps
yay -Syu                  # full system upgrade
yay -Ss <term>            # search
yay -Qi <package>         # local package info
```

## Common Useful Aliases (agent should know these)
```bash
yayf         # fzf-powered interactive package search + install
docker-clean # prune containers, images, networks, volumes
topcpu       # top 10 CPU-consuming processes
openports    # active inet ports (netstat)
da           # formatted date string
h '<term>'   # search bash history
p '<term>'   # grep running processes
```

## Do NOTs
- **Do not use `rm`** expecting permanent deletion — it calls `trash`. Use `/bin/rm` explicitly when deletion is required.
- **Do not assume zsh** — no zsh installed. Bash-only syntax.
- **Do not use `apt-get`** — Arch uses pacman/yay (the alias exists but is misleading if invoked)
- **Do not pipe through `cat` or `grep`** without considering the bat/rg aliases
- **Do not call `ollama`** locally — it is not installed on totharchy; it runs on the Mac Mini
- **Do not blindly `systemctl restart`** user services without `--user` flag for user-scoped units
- **Do not edit symlinked dotfiles in place** — changes should go through the dotfiles source repo

## Hyprland / Wayland Notes
- Display server: Wayland (no Xorg)
- `WAYLAND_DISPLAY` is set; X11-only tools may fail
- Notifications: `notify-send` routes through `mako`
- Clipboard: use `wl-copy` / `wl-paste` (not xclip/xsel)
- Screenshots: use `hyprshot` or `grimblast` if available
