from __future__ import annotations

import secrets
import subprocess

from flask import Flask, redirect, render_template, request, url_for

from flysight import config, device, jobs, mtools, sudo_auth


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

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

    @app.route("/copy", methods=["POST"])
    def copy():
        path = request.form["path"]
        dest = request.form["dest"]
        dev = device.detect_or_400()
        job_id = jobs.start_copy(dev.raw_node, path, dest)
        return redirect(url_for("jobs_view", highlight=job_id))

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


if __name__ == "__main__":
    cfg = config.get()
    create_app().run(host=cfg.server.host, port=cfg.server.port, debug=False)
