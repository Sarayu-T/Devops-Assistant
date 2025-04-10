from flask import Flask, request, jsonify
from threading import Timer
from datetime import datetime
import time
import uuid

from utils.jenkins import get_latest_failed_build, get_github_repo_and_sha, get_full_console_log, trigger_rollback
from utils.github import get_developers_up_to_commit
from utils.emailer import send_email

app = Flask(__name__)


fixes = {} # TODO: add db instead


FAILED_FILE_PATH = "src/main.py" # TODO: Fetch it from LLM

@app.route("/trigger", methods=["POST"])
def trigger_alert():
    latest_failed_build = get_latest_failed_build()
    if not latest_failed_build:
        return jsonify({"error": "No failed builds found."}), 404

    github_repo, commit_sha = get_github_repo_and_sha(latest_failed_build)
    if not github_repo:
        return jsonify({"error": "Failed to determine GitHub repository."}), 500

    developers = get_developers_up_to_commit(github_repo, FAILED_FILE_PATH, commit_sha)
    emails = [dev.split("<")[1].strip(" >") for dev in developers if "<" in dev]


    fix_id = str(uuid.uuid4())
    fixes[fix_id] = {
        "developers": emails,
        "votes": {},
        "file_path": FAILED_FILE_PATH,
        "build_number": latest_failed_build,
        "start_time": time.time()
    }

    email_status = send_email(emails, FAILED_FILE_PATH, latest_failed_build, fix_id)
    console_log = get_full_console_log(latest_failed_build)

    # Start 1hr countdown timer to evaluate votes
    Timer(3600, evaluate_votes, args=(fix_id,)).start()

    return jsonify({
        "fix_id": fix_id,
        "build": latest_failed_build,
        "repo": github_repo,
        "developers": developers,
        "email_status": email_status,
        "console_log": console_log,
    })


@app.route("/vote")
def vote():
    fix_id = request.args.get("fix_id")
    email = request.args.get("email")
    vote = request.args.get("vote")

    if fix_id not in fixes:
        return "Invalid fix ID", 400

    # Prevent duplicate voting
    if email in fixes[fix_id]["votes"]:
        return f"You already voted: {fixes[fix_id]['votes'][email]}", 200

    fixes[fix_id]["votes"][email] = vote
    return f"Thanks {email}, your vote ({vote}) has been recorded."


def evaluate_votes(fix_id):
    if fix_id not in fixes:
        print(f"[{fix_id}] Fix ID not found.")
        return

    fix = fixes[fix_id]
    total = len(fix["developers"])
    votes = fix["votes"]
    approvals = sum(1 for v in votes.values() if v == "approve")

    print(f"[{fix_id}] Evaluating votes: {approvals}/{total} approvals")

    if approvals > total / 2:
        print(f"[{fix_id}] Majority approved. Proceeding with fix (build #{fix['build_number']}).")
        #TODO: add logic to apply the fix
    else:
        print(f"[{fix_id}] ❌ Not enough approval. Rolling back...")
        trigger_rollback()
        # TODO: Notify developers via email that rollback was triggered

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
