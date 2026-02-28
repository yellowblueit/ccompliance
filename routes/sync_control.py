import threading
from flask import Blueprint, render_template, request, session, jsonify, current_app
from routes import login_required, require_permission
from services.sync_service import run_sync, get_log_entries, is_sync_running, get_last_sync_result, request_sync_cancel
from services.scheduler_service import get_scheduler_status

sync_bp = Blueprint("sync", __name__)


@sync_bp.route("/")
@login_required
def index():
    scheduler_status = get_scheduler_status()
    last_result = get_last_sync_result()
    logs = get_log_entries(100)
    return render_template("sync/control.html",
                           scheduler_status=scheduler_status,
                           last_result=last_result,
                           logs=logs,
                           sync_running=is_sync_running(),
                           user=session.get("user", {}))


@sync_bp.route("/trigger", methods=["POST"])
@login_required
@require_permission("manage_sync")
def trigger():
    if is_sync_running():
        return jsonify({"error": "Sync already running"}), 409

    config = current_app.config.get("APP_CONFIG", {})
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            run_sync(config)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@sync_bp.route("/stop", methods=["POST"])
@login_required
@require_permission("manage_sync")
def stop():
    if not is_sync_running():
        return jsonify({"error": "No sync is currently running"}), 409
    request_sync_cancel()
    return jsonify({"status": "cancel_requested"})


@sync_bp.route("/log")
@login_required
def log():
    limit = request.args.get("limit", 100, type=int)
    entries = get_log_entries(limit)
    return jsonify({
        "running": is_sync_running(),
        "entries": entries,
        "last_result": get_last_sync_result(),
    })
