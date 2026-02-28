import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, session, current_app, jsonify
from routes import login_required, get_anthropic_client
from routes.activities import ACTIVITY_TYPE_CATEGORIES

dashboard_bp = Blueprint("dashboard", __name__)

# Module-level cache for dashboard activity stats
_stats_cache = {"data": None, "ts": 0}
_STATS_CACHE_TTL = 120  # seconds


@dashboard_bp.route("/dashboard")
@login_required
def index():
    config = current_app.config["APP_CONFIG"]

    archive_user_ids = config.get("archive_user_ids", [])
    archive_all = config.get("archive_all_users", False)

    status = {
        "anthropic_configured": bool(config.get("anthropic_compliance_access_key")),
        "graph_configured": all([
            config.get("graph_tenant_id"),
            config.get("graph_client_id"),
            config.get("graph_client_secret"),
        ]),
        "sync_enabled": config.get("sync_enabled", False),
        "mailbox_configured": bool(config.get("compliance_mailbox")),
        "storage_configured": bool(config.get("storage_connection_string")),
        "archive_all": archive_all,
        "archive_user_count": len(archive_user_ids) if not archive_all else None,
    }

    org_count = None
    api_error = None
    if status["anthropic_configured"]:
        try:
            client = get_anthropic_client()
            orgs = client.list_organizations()
            org_data = orgs if isinstance(orgs, list) else orgs.get("data", [])
            org_count = len(org_data)
        except Exception as e:
            api_error = str(e)

    return render_template("dashboard.html",
                           user=session.get("user", {}),
                           status=status,
                           org_count=org_count,
                           api_error=api_error,
                           config=config)


@dashboard_bp.route("/dashboard/api/activity-stats")
@login_required
def api_activity_stats():
    global _stats_cache
    now = time.time()

    if _stats_cache["data"] and (now - _stats_cache["ts"]) < _STATS_CACHE_TTL:
        return jsonify(_stats_cache["data"])

    client = get_anthropic_client()
    if not client:
        return jsonify({"error": "Anthropic API not configured"})

    config = current_app.config["APP_CONFIG"]
    tz_name = config.get("display_timezone", "UTC")
    try:
        display_tz = ZoneInfo(tz_name)
    except Exception:
        display_tz = ZoneInfo("UTC")
        tz_name = "UTC"

    # Reverse lookup: activity type -> category name
    type_to_category = {}
    for cat, types in ACTIVITY_TYPE_CATEGORIES.items():
        for t in types:
            type_to_category[t] = cat

    # "Today" in the display timezone, converted to UTC for the API query
    local_now = datetime.now(display_tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = local_midnight.astimezone(timezone.utc).isoformat()

    all_activities = []
    after_id = None

    try:
        for _ in range(10):  # max 10 pages x 100 = 1000 activities
            kwargs = {"created_at_gte": today_start_utc, "limit": 100}
            if after_id:
                kwargs["after_id"] = after_id
            result = client.list_activities(**kwargs)
            all_activities.extend(result.get("data", []))
            if not result.get("has_more") or not result.get("last_id"):
                break
            after_id = result["last_id"]
    except Exception as e:
        return jsonify({"error": str(e)})

    # Hourly breakdown for today (in display timezone)
    hourly_counts = defaultdict(int)
    category_counts = defaultdict(int)
    actor_counts = defaultdict(int)

    for a in all_activities:
        created = a.get("created_at", "")
        if created:
            try:
                utc_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                local_dt = utc_dt.astimezone(display_tz)
                hourly_counts[f"{local_dt.hour:02d}"] += 1
            except (ValueError, TypeError):
                pass

        cat = type_to_category.get(a.get("type", ""), "Other")
        category_counts[cat] += 1

        actor = a.get("actor") or {}
        email = (actor.get("email_address")
                 or actor.get("unauthenticated_email_address")
                 or actor.get("api_key_id")
                 or "unknown")
        actor_counts[email] += 1

    # Build hourly series (0-23, zero-filled up to current local hour)
    now_hour = local_now.hour
    hourly = [{"hour": f"{h:02d}:00", "count": hourly_counts.get(f"{h:02d}", 0)}
              for h in range(now_hour + 1)]

    # Categories with counts > 0
    cat_labels = list(ACTIVITY_TYPE_CATEGORIES.keys())
    if category_counts.get("Other", 0) > 0:
        cat_labels.append("Other")
    categories = [{"category": c, "count": category_counts.get(c, 0)}
                  for c in cat_labels if category_counts.get(c, 0) > 0]

    # Top 10 actors
    top_actors = sorted(actor_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    actors = [{"user": a[0], "count": a[1]} for a in top_actors]

    # Timezone abbreviation for display
    tz_abbr = local_now.strftime("%Z") or tz_name

    payload = {
        "total": len(all_activities),
        "hourly": hourly,
        "categories": categories,
        "top_actors": actors,
        "tz_abbr": tz_abbr,
    }

    _stats_cache = {"data": payload, "ts": now}
    return jsonify(payload)
