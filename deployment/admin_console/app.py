"""Flask app for the SiLA 2 Deployment Admin Console."""
from __future__ import annotations

import json
import time
from typing import Any, Dict

from flask import Flask, Response, jsonify, render_template, request

from . import ansible_runner, inventory


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Dashboard ──────────────────────────────────────────────────────

    @app.route("/")
    def dashboard():
        hosts = inventory.load_inventory()
        groups = inventory.get_groups()
        all_vars = inventory.load_all_vars()
        return render_template(
            "dashboard.html",
            hosts=hosts,
            groups=groups,
            all_vars=all_vars,
        )

    # ── Inventory API ──────────────────────────────────────────────────

    @app.route("/api/inventory")
    def api_inventory():
        return jsonify(inventory.load_inventory())

    @app.route("/api/groups")
    def api_groups():
        return jsonify(inventory.get_groups())

    # ── Playbook Actions ───────────────────────────────────────────────

    @app.route("/api/action/deploy", methods=["POST"])
    def api_deploy():
        data = request.json or {}
        limit = data.get("limit", "")
        job = ansible_runner.run_playbook("deploy.yml", limit=limit)
        return jsonify({"job_id": job.id})

    @app.route("/api/action/update", methods=["POST"])
    def api_update():
        data = request.json or {}
        limit = data.get("limit", "")
        job = ansible_runner.run_playbook("update.yml", limit=limit)
        return jsonify({"job_id": job.id})

    @app.route("/api/action/status", methods=["POST"])
    def api_status_check():
        data = request.json or {}
        limit = data.get("limit", "")
        job = ansible_runner.run_playbook("status.yml", limit=limit)
        return jsonify({"job_id": job.id})

    @app.route("/api/action/uninstall", methods=["POST"])
    def api_uninstall():
        data = request.json or {}
        limit = data.get("limit", "")
        job = ansible_runner.run_playbook("uninstall.yml", limit=limit)
        return jsonify({"job_id": job.id})

    @app.route("/api/action/tailscale", methods=["POST"])
    def api_tailscale():
        data = request.json or {}
        limit = data.get("limit", "")
        job = ansible_runner.run_playbook("tailscale.yml", limit=limit)
        return jsonify({"job_id": job.id})

    # ── Job Output ─────────────────────────────────────────────────────

    @app.route("/api/jobs")
    def api_jobs():
        jobs = ansible_runner.list_jobs()
        return jsonify([
            {
                "id": j.id,
                "playbook": j.playbook,
                "limit": j.limit,
                "status": j.status,
                "elapsed": j.elapsed(),
                "return_code": j.return_code,
            }
            for j in jobs
        ])

    @app.route("/api/jobs/<job_id>")
    def api_job_detail(job_id: str):
        job = ansible_runner.get_job(job_id)
        if job is None:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({
            "id": job.id,
            "playbook": job.playbook,
            "limit": job.limit,
            "status": job.status,
            "output": "".join(job.output_lines),
            "return_code": job.return_code,
            "elapsed": job.elapsed(),
        })

    @app.route("/api/jobs/<job_id>/stream")
    def api_job_stream(job_id: str):
        """SSE stream of job output lines."""
        job = ansible_runner.get_job(job_id)
        if job is None:
            return jsonify({"error": "Job not found"}), 404

        def generate():
            sent = 0
            while True:
                lines = job.output_lines[sent:]
                for line in lines:
                    yield f"data: {json.dumps({'line': line})}\n\n"
                    sent += 1
                if job.status in ("completed", "failed"):
                    yield f"data: {json.dumps({'done': True, 'status': job.status, 'return_code': job.return_code})}\n\n"
                    break
                time.sleep(0.3)

        return Response(generate(), mimetype="text/event-stream")

    # ── Job Output Page ────────────────────────────────────────────────

    @app.route("/job/<job_id>")
    def job_page(job_id: str):
        job = ansible_runner.get_job(job_id)
        return render_template("job_output.html", job=job, job_id=job_id)

    # ── Wizards ────────────────────────────────────────────────────────

    @app.route("/wizard/tailscale")
    def wizard_tailscale():
        hosts = inventory.load_inventory()
        groups = inventory.get_groups()
        return render_template("wizard_tailscale.html", hosts=hosts, groups=groups)

    @app.route("/wizard/cloudrun")
    def wizard_cloudrun():
        return render_template("wizard_cloudrun.html")

    @app.route("/wizard/add-host")
    def wizard_add_host():
        groups = inventory.get_groups()
        return render_template("wizard_add_host.html", groups=groups)

    return app
