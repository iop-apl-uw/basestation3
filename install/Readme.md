# Automated basestation3 install/update scripts

**NOTE** These scripts are highly experimental and not yet considered appropriate for general use.

`install_basestation.sh` and `update_basestation.sh` automate the steps
described in the main [Readme.md](../Readme.md)'s "Installation for a
realtime basestation" section - system packages, the `gliders` group, the
PAM login edit, the `/usr/local/basestation3` checkout, the `uv` venv setup,
Chromium (needed by kaleido for static plot image export - see
[Installing Chromium](../Readme.md#installing-chromium)), and the
login/logout scripts.

## install_basestation.sh

Fresh install, from system packages through
[login/logout scripts](../Readme.md#loginlogout-scripts):

    sudo install/install_basestation.sh --pilot-user <user>

## update_basestation.sh

Updates an existing install (git pull the source, re-sync the `uv` venv,
re-check Chromium, refresh the login/logout scripts if they haven't been
hand-edited), without repeating the one-time group/PAM/package steps:

    sudo install/update_basestation.sh --pilot-user <user>

## What these scripts do not cover

- chroot jail setup (see [Jail ReadMe.md](../jail/ReadMe.md))
- Basestation2 coexistence
- the optional `rawxfer`/Sensors extension builds
- the external repos (seaglider_lrzsz, rudicsd)
- modem/mgetty setup
- commissioning a glider account (`Commission.py`, still run manually - see
  [Commissioning a new glider](../Readme.md#commissioning-a-new-glider))

Those remain manual, advanced steps documented in the main
[Readme.md](../Readme.md). The manual walkthrough there is also the
reference for what these scripts do under the hood, useful if a script
fails partway through.
