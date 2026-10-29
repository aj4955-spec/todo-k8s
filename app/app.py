import os
import re
import socket
import logging

from prometheus_flask_exporter import PrometheusMetrics
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson.objectid import ObjectId
from bson.errors import InvalidId

# ---- Settings, read from environment variables ----
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "todo_db")
APP_VERSION = os.environ.get("APP_VERSION", "dev")
ENABLE_CHAOS = os.environ.get("ENABLE_CHAOS", "false").lower() == "true"
UNHEALTHY_FLAG = "/tmp/unhealthy"
POD_NAME = socket.gethostname()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

# ---- Database connection: give up after 2 seconds, not 30 ----
client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=2000,
    connectTimeoutMS=2000,
    socketTimeoutMS=5000,
)
db = client[MONGO_DB]
todos = db.todo

app = Flask(__name__)
metrics = PrometheusMetrics(app, excluded_paths=["/healthz", "/readyz", "/metrics"])
title = "TODO with Flask"
heading = "ToDo Reminder"

SEARCHABLE_FIELDS = {"id", "name", "desc", "date", "pr"}


@app.context_processor
def inject_build_info():
    """Makes the version and pod name available to every template (shown in the footer)."""
    return {"app_version": APP_VERSION, "pod_name": POD_NAME}


def redirect_url():
    """Where to go back to after an action: ?next=, then the previous page, then home."""
    return request.args.get("next") or request.referrer or url_for("tasks")


# ---- Error handling: every error gets a friendly page, never a crash dump ----
def error_page(code, message):
    return render_template("error.html", code=code, message=message, t=title, h=heading), code


@app.errorhandler(PyMongoError)
def handle_db_error(e):
    app.logger.error("Database error: %s", e)
    return error_page(503, "The database is unavailable right now. Please try again in a few seconds.")


@app.errorhandler(400)
def handle_400(e):
    return error_page(400, getattr(e, "description", None) or "That request looks wrong.")


@app.errorhandler(404)
def handle_404(e):
    return error_page(404, getattr(e, "description", None) or "We couldn't find that page or task.")


@app.errorhandler(405)
def handle_405(e):
    return error_page(405, "That action isn't allowed here.")


@app.errorhandler(500)
def handle_500(e):
    app.logger.exception("Unexpected error")
    return error_page(500, "Something went wrong on our side.")


def parse_object_id(raw):
    """Turn a task id from the URL into an ObjectId, or reply 400 if it's junk."""
    try:
        return ObjectId(raw)
    except (InvalidId, TypeError):
        abort(400, description="That task id isn't valid.")


def get_task_or_404(task_id):
    """Fetch one task by id, or reply 404 if it doesn't exist."""
    task = todos.find_one({"_id": task_id})
    if task is None:
        abort(404, description="That task doesn't exist (it may have been deleted).")
    return task


def read_task_form():
    """Read the add/edit form, trimming spaces. Task name is required."""
    data = {
        "name": (request.values.get("name") or "").strip(),
        "desc": (request.values.get("desc") or "").strip(),
        "date": (request.values.get("date") or "").strip(),
        "pr": (request.values.get("pr") or "").strip(),
    }
    if not data["name"]:
        abort(400, description="Please give the task a name.")
    return data


# ---- Health endpoints used by Kubernetes probes ----
@app.route("/healthz")
def healthz():
    """Liveness: is the app process itself OK? Never touches the database."""
    if os.path.exists(UNHEALTHY_FLAG):
        return jsonify(status="unhealthy"), 500
    return jsonify(status="ok"), 200


@app.route("/readyz")
def readyz():
    """Readiness: can the app actually serve users right now? Checks the database."""
    try:
        client.admin.command("ping")
        return jsonify(status="ready"), 200
    except PyMongoError as e:
        app.logger.warning("Readiness check failed: %s", e)
        return jsonify(status="not ready", reason="database unreachable"), 503


@app.route("/version")
def version():
    """Which version is running, and on which pod? Handy for rolling update demos."""
    return jsonify(version=APP_VERSION, pod=POD_NAME)


# ---- Chaos switches for the Part 7 probe demo (only when ENABLE_CHAOS=true) ----
@app.route("/chaos/fail-liveness", methods=["POST"])
def chaos_fail_liveness():
    if not ENABLE_CHAOS:
        abort(404)
    open(UNHEALTHY_FLAG, "w").close()
    app.logger.warning("Chaos: liveness will now fail on pod %s", POD_NAME)
    return jsonify(status="liveness will now fail", pod=POD_NAME), 200


@app.route("/chaos/recover", methods=["POST"])
def chaos_recover():
    if not ENABLE_CHAOS:
        abort(404)
    if os.path.exists(UNHEALTHY_FLAG):
        os.remove(UNHEALTHY_FLAG)
    return jsonify(status="recovered", pod=POD_NAME), 200


# ---- To Do pages (same behavior as the starter app) ----
@app.route("/list")
def lists():
    # Display all tasks
    todos_l = todos.find()
    return render_template("index.html", a1="active", todos=todos_l, t=title, h=heading)


@app.route("/")
@app.route("/uncompleted")
def tasks():
    # Display uncompleted tasks
    todos_l = todos.find({"done": "no"})
    return render_template("index.html", a2="active", todos=todos_l, t=title, h=heading)


@app.route("/completed")
def completed():
    # Display completed tasks
    todos_l = todos.find({"done": "yes"})
    return render_template("index.html", a3="active", todos=todos_l, t=title, h=heading)


@app.route("/done")
def done():
    # Toggle a task between done and not done
    task_id = parse_object_id(request.values.get("_id"))
    task = get_task_or_404(task_id)
    new_state = "no" if task.get("done") == "yes" else "yes"
    todos.update_one({"_id": task_id}, {"$set": {"done": new_state}})
    return redirect(redirect_url())


@app.route("/action", methods=["POST"])
def action():
    # Add a task
    data = read_task_form()
    data["done"] = "no"
    todos.insert_one(data)
    return redirect("/list")


@app.route("/remove")
def remove():
    # Delete a task
    task_id = parse_object_id(request.values.get("_id"))
    result = todos.delete_one({"_id": task_id})
    if result.deleted_count == 0:
        abort(404, description="That task doesn't exist (it may already be deleted).")
    return redirect("/")


@app.route("/update")
def update():
    # Show the edit form for one task
    task_id = parse_object_id(request.values.get("_id"))
    task = get_task_or_404(task_id)
    return render_template("update.html", tasks=[task], h=heading, t=title)


@app.route("/action3", methods=["POST"])
def action3():
    # Save an edited task
    task_id = parse_object_id(request.values.get("_id"))
    data = read_task_form()
    result = todos.update_one({"_id": task_id}, {"$set": data})
    if result.matched_count == 0:
        abort(404, description="That task doesn't exist (it may have been deleted).")
    return redirect("/")


@app.route("/search", methods=["GET"])
def search():
    # Search tasks by id, name, description, date or priority
    key = (request.values.get("key") or "").strip()
    refer = request.values.get("refer") or ""

    if refer not in SEARCHABLE_FIELDS:
        abort(400, description="You can only search by id, name, description, date or priority.")
    if not key:
        return redirect("/list")

    if refer == "id":
        try:
            query = {"_id": ObjectId(key)}
        except InvalidId:
            todos_l = todos.find()
            return render_template("index.html", a1="active", todos=todos_l, t=title, h=heading,
                                   error="Invalid id format. An id is a 24 character code like 6720a1b2c3d4e5f601234567.")
        if todos.count_documents(query) == 0:
            todos_l = todos.find()
            return render_template("index.html", a1="active", todos=todos_l, t=title, h=heading,
                                   error="No task with that id exists.")
    else:
        # Case insensitive "contains" search; re.escape stops special characters being treated as regex
        query = {refer: {"$regex": re.escape(key), "$options": "i"}}

    todos_l = todos.find(query)
    return render_template("searchlist.html", todos=todos_l, t=title, h=heading)


@app.route("/about")
def about():
    return render_template("credits.html", t=title, h=heading)


if __name__ == "__main__":
    # Local runs only. In Docker and Kubernetes, gunicorn starts the app instead.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
