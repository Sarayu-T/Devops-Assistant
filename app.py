from flask import Flask, request, jsonify
from utils.jenkins import get_latest_failed_build, get_github_repo_and_sha, get_full_console_log
from utils.github import get_developers_up_to_commit
from utils.emailer import send_email

app = Flask(__name__)

# 🔹 Hardcoded File Name
FAILED_FILE_PATH = "src/main.py" #TODO: fetch it from LLM

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
    email_status = send_email(emails, FAILED_FILE_PATH, latest_failed_build)
    console_log = get_full_console_log(latest_failed_build)

    return jsonify({
        "build": latest_failed_build,
        "repo": github_repo,
        "developers": developers,
        "email_status": email_status,
        "console_log": console_log,
    })

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
