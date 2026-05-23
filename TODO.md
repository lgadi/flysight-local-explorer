# TODO

Things v1 deliberately doesn't do, ordered by priority. P1 items have
visible day-to-day payoff and are reasonable in scope; P4 is eng polish
that doesn't move the user experience.

## P1 — do next

- [x] **Sortable column headers in browse view.** Clickable
      Name / Size / Modified headers that toggle ascending / descending.
      Directories are still grouped first within each sort; date sort
      tolerates the "1980-00-00" bogus-RTC marker by sorting it before
      any real date.
- [x] **Auto-refresh browse view when a job touches it.** Toast at the
      top of the browse page polls `/jobs/snapshot.json` every 4 s, fires
      when any in-flight job transitions to done/error, and highlights
      green when the finished job is an upload to the current path (i.e.
      the user probably wants to see new files).
- [x] **Per-byte progress for long copies.** Pre-computes total bytes
      via `mtools.tree_size` (recursive `mdir -/` sum) for copy jobs and
      from staging file sizes for upload jobs. Copy jobs run a 1-second
      watcher thread that walks the destination to report bytes-written;
      upload jobs increment as `Copying X` lines arrive, keyed by the
      file's basename. UI prefers bytes-based progress and falls back to
      file count when total bytes is unknown.

## P2 — quality of life

- [ ] **Bulk multi-select.** Add a checkbox to each entry row, a sticky
      action bar with "Copy selected to…" and "Delete selected". Server-
      side that's just looping the existing single-entry endpoints, but
      it needs queueing so one user click doesn't kick off 30 mtools
      processes at once. The existing `_op_lock` handles the serialisation;
      we just need to dispatch the loop on a worker thread.
- [ ] **User-configurable default copy destination.** Today
      `_default_dest_for` in `app.py` hardcodes `~/Downloads/flysight/`.
      Should be a settings page (or at minimum an env var) that lets
      the user set their preferred root once, with the per-copy stamp
      still appended. Persist to a small JSON file in `~/.config/`.
- [ ] **Eject button.** Run `diskutil eject /dev/disk4` so the FlySight
      can be unplugged cleanly from the UI.
- [ ] **"Back to browse" button on completed jobs.** Once a job's
      status is `done` or `error`, the jobs-view card should grow a
      button that navigates to `/?path=<fat_path>` (the source dir for
      copies, the destination dir for uploads). Right now the user has
      to use the header nav, which is one hop more than necessary.
- [ ] **Touch button for folders with bogus 1980-00-00 dates.** When
      the FlySight's RTC isn't set, the dirs it creates get stamped
      with date 0 / time 0, and mdir renders that as `1980-00-00 0:00`.
      Add a "fix date" action per affected folder that sets its mtime
      to either today, or to a date parsed from the folder name when
      it matches the `YY-MM-DD` convention FlySight uses (e.g.
      `26-05-22` → `2026-05-22`). Implementation: mtools has no touch
      command, so we'd write the FAT32 directory entry directly —
      bytes 0x16-0x19 of the 32-byte entry hold mtime (date + time
      encoded per the FAT spec). Walking the directory chain by hand
      is doable but fiddly; alternatives are `pyfat` (Python lib) or
      `fattools`. UI surfaces the action only for entries whose mtime
      is the literal 1980-00-00 sentinel.
- [ ] **Move runtime knobs to a `config.toml` file.** Today values
      like the expected partition label, the server port, the default
      download root, and various caps are hardcoded in source. A small
      TOML file (search order `./config.toml` → `~/.config/flysight-local-explorer/config.toml`)
      loaded at startup via `tomllib` should drive these, with sensible
      defaults baked in so a missing file is fine:

      | Section | Key | Default | What |
      |---|---|---|---|
      | `[device]` | `label` | `"FLYSIGHT"` | Partition label to auto-detect |
      | `[device]` | `fallback_to_first_fat` | `false` | If labeled disk isn't found, use the first external FAT under `max_size_gb` |
      | `[device]` | `max_size_gb` | `64` | Upper bound for the fallback heuristic |
      | `[server]` | `host` | `"127.0.0.1"` | Bind address (keep localhost by default) |
      | `[server]` | `port` | `5000` | Bind port |
      | `[ui]` | `default_download_root` | `"~/Downloads/flysight"` | Used by `_default_dest_for` |
      | `[ui]` | `browse_poll_seconds` | `4` | Browse-page job-poll interval |
      | `[security]` | `sudo_idle_timeout_minutes` | `30` | `0` disables; pairs with the sudo-timeout item in P3 |
      | `[jobs]` | `max_history` | `50` | Cap on jobs kept in the in-process registry |
      | `[jobs]` | `max_log_lines` | `500` | Cap on per-job log buffer |

      Also ship a `config.example.toml` in the repo with the defaults
      documented inline. This supersedes the *user-configurable default
      copy destination* item above and is the storage backend for the
      *label fallback* and *sudo idle timeout* items in P3.

## P3 — robustness

- [ ] **Friendly errors when mtools isn't installed** or when sudo is
      revoked mid-session. Currently surfaces as a raw `MToolsError`.
- [ ] **Session timeout for the cached sudo password.** Right now it
      lives forever until process exit. A 30-minute idle timeout would
      match macOS's own sudo policy and reduce the window if someone
      grabs the laptop.
- [ ] **Fallback when the partition isn't labeled `FLYSIGHT`.** Today
      `EXPECTED_LABEL` is hardcoded in `flysight/device.py`. Could
      auto-pick the first external FAT partition under, say, 64 GB if
      the labeled one isn't present, behind a config flag.
- [ ] **Handle multiple FlySights connected at once.** Device picker
      in the header. Today we just take the first FAT partition labeled
      `FLYSIGHT` we find.
- [ ] **Inline file previews.** Mostly TRACK.CSV / SENSOR.CSV as a small
      tabular view, CONFIG.TXT as text, and .UBX as a hex dump
      (first/last N KB). Needs a `/preview?path=&range=` endpoint that
      streams via `mcopy ... -` with a byte cap.

## P4 — engineering

- [ ] **Type checking and linting** (`ruff`, `mypy`) wired into a
      `pre-commit` config.
- [ ] **Tests.** `flysight/mtools._parse_mdir` is the obvious unit-test
      target (deterministic input/output). `device.detect()` is a good
      candidate for parametrised tests with frozen plist samples.
- [ ] **Bound the in-process job history.** `jobs._order` already caps
      at 50, but `Job.log` is bounded per-job; the registry should also
      persist completed-job rows to disk if we want history across
      restarts. Probably YAGNI for a personal tool.

## Speculative / future direction

- [ ] **Consider converting to a native macOS app.** The Flask web app
      is the right MVP, but a native shell would integrate better with
      macOS (dock icon, real `NSOpenPanel` for picking download
      destinations, Keychain for the sudo password, optionally
      bypassing `mtools` by talking to DiskArbitration / IOKit
      directly). Paths in roughly increasing rewrite cost:

      - **pywebview** — wraps a native `WKWebView` around the existing
        Flask app. Smallest delta; mostly a packaging win.
      - **Tauri / Electron** — bundle the web UI as a standalone app
        with the venv and `mtools` embedded; can be signed and
        notarized for distribution.
      - **PyObjC** — native AppKit app in Python. Drops the web stack
        but keeps the language.
      - **SwiftUI** — full rewrite in Swift, best native feel. Lets
        us use Apple frameworks to read/write the FAT volume directly,
        which would also remove the `sudo` dance.

      Worth doing only if this becomes a regular daily tool, not just
      for occasional log pulls.
