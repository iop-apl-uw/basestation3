# Live-demo Docker container

**NOTE** For demoing/teaching the "## Installation" section of the main
[Readme.md](../Readme.md#installation) by hand over SSH. Not a production
install path - see [install/](../install/Readme.md) for that.

`start_demo_container.sh` starts a throwaway `ubuntu:22.04` container and
stages it through the main [Readme.md](../Readme.md)'s "Basestation source"
section - the same system packages, `gliders` group, PAM login edit, and
`/usr/local/basestation3` checkout that `install/install_basestation.sh`
sets up, by calling the same [install/lib_install.sh](../install/lib_install.sh)
functions (see [stage_prereqs.sh](stage_prereqs.sh)). It stops there, so a
live demo can start typing right at the
["## Installation"](../Readme.md#installation) heading: installing `uv`,
creating the `uv`-managed venv, `uv sync`, and the login/logout scripts.

## Usage

    demo/start_demo_container.sh [--pilot-user <user>] [--port <port>]

Prints an `ssh <user>@localhost -p <port>` command once ready. If a public
key exists on the host (`~/.ssh/id_ed25519.pub` or `id_rsa.pub`), it's
installed for the pilot user and login is key-based; otherwise a random
password is generated and printed once. sshd is bound to `127.0.0.1` only.

Tear down with:

    demo/stop_demo_container.sh

## Caveats

- The pilot user is granted **passwordless sudo** inside the container -
  fine for a throwaway teaching container, not something to imitate on a
  real basestation.
- `/usr/local/basestation3` inside the container is a fresh `git clone` of
  this checkout's current commit (via a read-only bind mount at `/src`), so
  uncommitted local changes aren't reflected.
- Everything else uncovered by `install_basestation.sh` - chroot jail setup,
  Basestation2 coexistence, `rawxfer`/Sensors builds, external repos, modem
  setup, `Commission.py` - is also out of scope here; see
  [install/Readme.md](../install/Readme.md).
