# TODO

Things v1 deliberately doesn't do, in roughly the order I'd reach for them
if I were the next person back in this repo.

## UX

- [ ] **Per-byte progress for long copies.** Today the progress bar ticks
      once per file, so a single big file (a 200 MB `RAW.UBX` is common)
      can sit at the same percentage for minutes. mtools 4.0.49 doesn't
      have first-class progress output, but we could pipe `mcopy` output
      through `pv -n` for byte counts, or run a sibling thread that
      `stat`s the destination tempfile to estimate per-file progress.
- [ ] **Bulk multi-select.** Add a checkbox to each entry row, a sticky
      action bar with "Copy selected to…" and "Delete selected". Server-
      side that's just looping the existing single-entry endpoints, but
      it needs queueing so one user click doesn't kick off 30 mtools
      processes at once. The existing `_op_lock` handles the serialisation;
      we just need to dispatch the loop on a worker thread.
- [ ] **Auto-refresh of browse view when a job touches it.** Right now
      after an upload finishes, the user has to manually refresh the
      browse page to see the new files. Could be a `/jobs/active.json`
      poll from the browse template, or SSE.
- [ ] **Inline file previews.** Mostly TRACK.CSV / SENSOR.CSV as a small
      tabular view, CONFIG.TXT as text, and .UBX as a hex dump
      (first/last N KB). Needs a `/preview?path=&range=` endpoint that
      streams via `mcopy ... -` with a byte cap.
- [ ] **Eject button.** Run `diskutil eject /dev/disk4` so the FlySight
      can be unplugged cleanly from the UI.
- [ ] **User-configurable default copy destination.** Today
      `_default_dest_for` in `app.py` hardcodes `~/Downloads/flysight/`.
      Should be a settings page (or at minimum an env var) that lets
      the user set their preferred root once, with the per-copy stamp
      still appended. Persist to a small JSON file in `~/.config/`.
- [ ] **Sortable column headers in browse view.** Clickable
      Name / Size / Modified headers that toggle ascending / descending.
      Today the order is hardcoded (dirs first, then alphabetical case-
      insensitive in `_parse_mdir`).

## Robustness

- [ ] **Session timeout for the cached sudo password.** Right now it
      lives forever until process exit. A 30-minute idle timeout would
      match macOS's own sudo policy and reduce the window if someone
      grabs the laptop.
- [ ] **Friendly errors when mtools isn't installed** or when sudo is
      revoked mid-session. Currently surfaces as a raw `MToolsError`.
- [ ] **Handle multiple FlySights connected at once.** Device picker
      in the header. Today we just take the first FAT partition labeled
      `FLYSIGHT` we find.
- [ ] **Fallback when the partition isn't labeled `FLYSIGHT`.** Today
      `EXPECTED_LABEL` is hardcoded in `flysight/device.py`. Could
      auto-pick the first external FAT partition under, say, 64 GB if
      the labeled one isn't present, behind a config flag.

## Engineering

- [ ] **Tests.** `flysight/mtools._parse_mdir` is the obvious unit-test
      target (deterministic input/output). `device.detect()` is a good
      candidate for parametrised tests with frozen plist samples.
- [ ] **Type checking and linting** (`ruff`, `mypy`) wired into a
      `pre-commit` config.
- [ ] **Bound the in-process job history.** `jobs._order` already caps
      at 50, but `Job.log` is bounded per-job; the registry should also
      persist completed-job rows to disk if we want history across
      restarts. Probably YAGNI for a personal tool.
