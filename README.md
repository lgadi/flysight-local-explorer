# flysight-local-explorer

A small local web app for browsing and managing a FlySight 2 microSD card
that's connected over USB but won't mount in Finder (a common situation on
macOS Tahoe and later, where the userspace `fskit.msdos` extension is
stricter than the previous kernel driver about USB-MSC behavior).

Wraps the [`mtools`](https://www.gnu.org/software/mtools/) command line so
you can browse directories, copy files and folders to and from the card,
and delete entries without leaving the browser.

## Prerequisites

- macOS (tested on Tahoe / Darwin 25.5+)
- Python 3.11 or later
- [Homebrew](https://brew.sh) with `mtools` installed:
  ```
  brew install mtools
  ```
- A FlySight 2 connected via USB-C, currently presenting a FAT partition

## Setup

```
git clone <your-fork>
cd flysight-local-explorer
brew install mtools
mdir -V
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Running

The simplest invocation doesn't require activating the venv:

```
.venv/bin/python app.py
```

If you'd rather activate the venv first, use the file that matches your
shell — bash/zsh use `activate`, fish uses `activate.fish`:

```
# bash / zsh
source .venv/bin/activate

# fish
source .venv/bin/activate.fish

python app.py
```

Then open <http://127.0.0.1:5050/> in your browser. The first action you
take will prompt for your macOS account password — this is required so
the app can `sudo mcopy` / `sudo mdir` against the raw block device. The
password is kept in process memory only, never written to disk, and is
discarded when you stop the server.

To use a different port without editing config:

```
python app.py --port 5051
```

## Configuration

A `config.toml` is optional. If you want to override the partition
label, the server bind address, the default download root, or other
knobs, copy `config.example.toml` to one of these paths:

- `./config.toml` (next to `app.py`) — checked first
- `~/.config/flysight-local-explorer/config.toml`

…and uncomment the keys you want to change. The file is read once at
startup; anything you don't set falls back to the documented defaults.

## Security notes

- The server binds to `127.0.0.1` only; nothing on the network can reach it.
- Your `sudo` password is held in a module-level Python variable for the
  lifetime of the process. Restarting the server clears it. The password
  is never logged, never put in the Flask session cookie, and never
  serialised.
- `mdeltree` is irreversible. The UI requires you to type the folder name
  to confirm.

## Why this exists

See the firmware repo's notes on the Tahoe FSKit / USB-MSC mount issue.
Until the FlySight firmware ships fixes that make Apple's stricter
userspace mount path happy, this is the most pleasant way to work with
the card from a Mac that won't auto-mount it.
