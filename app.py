from __future__ import annotations

import secrets

from flask import Flask, redirect, render_template, request, url_for

from flysight import device, jobs, mtools, sudo_auth


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

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
            return render_template("no_device.html")
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

    @app.route("/jobs")
    def jobs_view():
        return render_template("jobs.html", jobs=jobs.all(), highlight=request.args.get("highlight"))

    @app.route("/jobs/<job_id>.json")
    def job_status(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            return {"error": "not_found"}, 404
        return job.as_dict()

    return app


def _crumbs(path: str) -> list[tuple[str, str]]:
    parts = [p for p in path.split("/") if p]
    crumbs = [("/", "FLYSIGHT")]
    running = ""
    for part in parts:
        running = f"{running}/{part}"
        crumbs.append((running, part))
    return crumbs


def _default_dest_for(path: str) -> str:
    import os
    from datetime import datetime

    leaf = path.strip("/").replace("/", "_") or "root"
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return os.path.expanduser(f"~/Downloads/flysight/{stamp}-{leaf}")


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
