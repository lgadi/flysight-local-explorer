from __future__ import annotations

import argparse
import secrets
import subprocess

from flask import Flask, redirect, render_template, request, url_for

from flysight import config, device, fat_ops, jobs, mtools, sudo_auth


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

    @app.template_filter("fix_date_for")
    def fix_date_for(folder_name: str) -> str:
        """Given a folder name, return YYYY-MM-DD: parsed from name if it
        matches the FlySight YY-MM-DD convention, otherwise today."""
        import re
        from datetime import date
        m = re.match(r"^(\d{2})-(\d{2})-(\d{2})$", folder_name or "")
        if m:
            yy, mm, dd = (int(x) for x in m.groups())
            try:
                return date(2000 + yy, mm, dd).isoformat()
            except ValueError:
                pass
        return date.today().isoformat()

    @app.template_filter("humanbytes")
    def humanbytes(n):
        if n is None:
            return "—"
        n = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if abs(n) < 1024 or unit == "TB":
                if unit == "B":
                    return f"{int(n)} B"
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    @app.before_request
    def require_auth():
        if request.endpoint in {"auth", "static"}:
            return None
        if not sudo_auth.is_set():
            return redirect(url_for("auth", next=request.full_path))
        return None

    @app.route("/auth", methods=["GET", "POST"])
    def auth():
        next_url = request.values.get("next") or url_for("index")
        if request.method == "POST":
            password = request.form.get("password", "")
            ok, err = sudo_auth.try_set(password)
            if ok:
                return redirect(next_url)
            return render_template("auth.html", error=err, next=next_url), 401
        return render_template("auth.html", error=None, next=next_url)

    @app.route("/logout", methods=["POST"])
    def logout():
        sudo_auth.clear()
        return redirect(url_for("auth"))

    @app.route("/")
    def index():
        path = request.args.get("path", "/")
        sort = request.args.get("sort", "name")
        direction = request.args.get("dir", "asc")
        if sort not in mtools.SORT_KEYS:
            sort = "name"
        if direction not in ("asc", "desc"):
            direction = "asc"
        dev = device.detect()
        if dev is None:
            return render_template("no_device.html", expected_label=config.get().device.label)
        try:
            entries = mtools.list_dir(dev.raw_node, path)
        except mtools.MToolsError as exc:
            return render_template("error.html", message=str(exc), device=dev), 500
        entries = mtools.sort_entries(entries, sort, direction)
        return render_template(
            "browse.html",
            device=dev,
            path=path,
            entries=entries,
            breadcrumbs=_crumbs(path),
            default_dest=_default_dest_for(path),
            jobs=jobs.recent(),
            sort=sort,
            direction=direction,
        )

    @app.route("/download")
    def download_file():
        path = request.args["path"]
        dev = device.detect_or_400()
        return mtools.stream_file(dev.raw_node, path)

    @app.route("/preview")
    def preview_file():
        path = request.args["path"]
        max_bytes = 256 * 1024  # 256 KB cap — fine for CONFIG/FLYSIGHT-sized text
        dev = device.detect_or_400()
        try:
            data = mtools.read_file_bytes(dev.raw_node, path, max_bytes)
        except mtools.MToolsError as exc:
            return str(exc), 500, {"Content-Type": "text/plain; charset=utf-8"}
        truncated = len(data) >= max_bytes
        body = data.decode("utf-8", errors="replace")
        return {
            "path": path,
            "bytes": len(data),
            "truncated": truncated,
            "content": body,
        }

    @app.route("/copy", methods=["POST"])
    def copy():
        path = request.form["path"]
        dest = request.form["dest"]
        dev = device.detect_or_400()
        job_id = jobs.start_copy(dev.raw_node, path, dest)
        return redirect(url_for("jobs_view", highlight=job_id))

    @app.route("/copy-bulk", methods=["POST"])
    def copy_bulk():
        items = request.form.getlist("selected")
        dest = request.form.get("dest", "")
        if not items or not dest:
            return redirect(request.referrer or url_for("index"))
        dev = device.detect_or_400()
        started: list[str] = []
        for item in items:
            kind, _, path = item.partition(":")
            if kind not in ("d", "f") or not path:
                continue
            started.append(jobs.start_copy(dev.raw_node, path, dest))
        if not started:
            return redirect(request.referrer or url_for("index"))
        return redirect(url_for("jobs_view", highlight=started[-1]))

    @app.route("/upload", methods=["POST"])
    def upload():
        dest = request.form["dest"]  # path on the card, e.g. /CONFIG.TXT or /AUDIO/
        files = request.files.getlist("files")
        dev = device.detect_or_400()
        job_id = jobs.start_upload(dev.raw_node, dest, files)
        return redirect(url_for("jobs_view", highlight=job_id))

    @app.route("/delete", methods=["POST"])
    def delete():
        path = request.form["path"]
        recursive = request.form.get("recursive") == "1"
        dev = device.detect_or_400()
        mtools.delete(dev.raw_node, path, recursive=recursive)
        parent = path.rsplit("/", 1)[0] or "/"
        return redirect(url_for("index", path=parent))

    @app.route("/touch", methods=["POST"])
    def touch():
        from datetime import date
        path = request.form["path"]
        new_date_str = request.form["new_date"]
        try:
            new_date = date.fromisoformat(new_date_str)
        except ValueError:
            return render_template("error.html", message=f"Invalid date: {new_date_str}", device=device.detect()), 400
        dev = device.detect_or_400()
        try:
            fat_ops.touch(dev.raw_node, path, new_date)
        except mtools.MToolsError as exc:
            return render_template("error.html", message=str(exc), device=dev), 500
        parent = path.rsplit("/", 1)[0] or "/"
        return redirect(url_for("index", path=parent))

    @app.route("/delete-bulk", methods=["POST"])
    def delete_bulk():
        items = request.form.getlist("selected")
        return_to = request.form.get("return_to") or "/"
        if not items:
            return redirect(url_for("index", path=return_to))
        dev = device.detect_or_400()
        errors: list[str] = []
        for item in items:
            kind, _, path = item.partition(":")
            if kind not in ("d", "f") or not path:
                continue
            try:
                mtools.delete(dev.raw_node, path, recursive=(kind == "d"))
            except mtools.MToolsError as exc:
                errors.append(f"{path}: {exc}")
        if errors:
            return render_template(
                "error.html",
                message="Bulk delete completed with errors:\n\n" + "\n".join(errors),
                device=dev,
            ), 500
        return redirect(url_for("index", path=return_to))

    @app.route("/eject", methods=["POST"])
    def eject():
        dev = device.detect_or_400()
        if not dev.whole_disk:
            return render_template("error.html", message="Couldn't determine the whole-disk node to eject.", device=dev), 500
        result = subprocess.run(
            ["diskutil", "eject", dev.whole_disk],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip() or result.stdout.decode(errors="replace").strip() or f"diskutil exited with status {result.returncode}"
            return render_template("error.html", message=err, device=dev), 500
        return render_template("no_device.html", ejected=True, ejected_label=dev.label)

    @app.route("/jobs")
    def jobs_view():
        return render_template("jobs.html", jobs=jobs.all(), highlight=request.args.get("highlight"))

    @app.route("/jobs/<job_id>.json")
    def job_status(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            return {"error": "not_found"}, 404
        return job.as_dict()

    @app.route("/jobs/snapshot.json")
    def jobs_snapshot():
        return {"jobs": jobs.snapshot()}

    @app.route("/jobs/events")
    def jobs_events():
        """Server-Sent Events stream of job-snapshot updates.

        Emits a `data:` event whenever the snapshot changes, and a
        comment-only line every ~25s as a keepalive so any intermediate
        proxy doesn't kill the idle connection. Internal poll interval
        is 1s; the actual HTTP connection stays open for the page
        lifetime."""
        import json
        import time

        from flask import Response, stream_with_context

        def gen():
            last_payload = None
            last_heartbeat = time.time()
            while True:
                payload = json.dumps({"jobs": jobs.snapshot()})
                now = time.time()
                if payload != last_payload:
                    yield f"data: {payload}\n\n"
                    last_payload = payload
                    last_heartbeat = now
                elif now - last_heartbeat > 25:
                    yield ": keepalive\n\n"
                    last_heartbeat = now
                time.sleep(1)

        return Response(
            stream_with_context(gen()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def _crumbs(path: str) -> list[tuple[str, str]]:
    parts = [p for p in path.split("/") if p]
    crumbs = [("/", "FLYSIGHT")]
    running = ""
    for part in parts:
        running = f"{running}/{part}"
        crumbs.append((running, part))
    return crumbs


def _default_dest_for(_path: str) -> str:
    """Default download destination: <root>/<YYYY-MM-DD>/. mcopy creates the
    source folder name as a subdir inside this, so e.g. copying ::/24-02-24
    on 2026-05-24 lands in ~/Downloads/flysight/2026-05-24/24-02-24/."""
    import os
    from datetime import datetime

    stamp = datetime.now().strftime("%Y-%m-%d")
    root = os.path.expanduser(config.get().ui.default_download_root)
    return os.path.join(root, stamp)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the FlySight local explorer web app.")
    parser.add_argument(
        "-p",
        "--port",
        type=_port,
        default=None,
        help="override the configured server port",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    cfg = config.get()
    port = args.port if args.port is not None else cfg.server.port
    create_app().run(host=cfg.server.host, port=port, debug=False)
