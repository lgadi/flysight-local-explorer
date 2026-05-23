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
- [ ] **Per-byte progress for long copies.** Today the progress bar
      ticks once per file, so a single big file (a 200 MB `RAW.UBX` is
      common) can sit at the same percentage for minutes. Pre-compute
      total bytes from `mdir`, then have a sibling thread `stat()` the
      destination tempfile to read bytes-written during the copy.

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
