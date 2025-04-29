from flask import Flask, request, jsonify,render_template
from threading import Timer
from datetime import datetime
import time
import uuid
import os
from dotenv import load_dotenv
from utils.jenkins import get_latest_failed_build, get_github_repo_and_sha, get_full_console_log, trigger_rollback
from utils.github import get_developers_up_to_commit
from utils.emailer import send_email
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

app = Flask(__name__)


fixes = {} # TODO: add db instead


FAILED_FILE_PATH = "src/main.py" # TODO: Fetch it from LLM

@app.route("/trigger", methods=["POST"])
def trigger_alert():
    latest_failed_build = get_latest_failed_build()
    if not latest_failed_build:
        return jsonify({"error": "No failed builds found."}), 404
    print(latest_failed_build)
    github_repo, commit_sha = get_github_repo_and_sha(latest_failed_build)
    if not github_repo:
        return jsonify({"error": "Failed to determine GitHub repository."}), 500

    developers = get_developers_up_to_commit(github_repo, FAILED_FILE_PATH, commit_sha)
    emails = [dev.split("<")[1].strip(" >") for dev in developers if "<" in dev]
    print(emails)


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
    Timer(60, evaluate_votes, args=(fix_id,)).start()

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


@app.route('/summary')
def show_summary():
    fix_id = request.args.get('fix_id')
    
    # Static summary data - replace with your actual data later
    summary_data = {
    "error_type": "SyntaxError",
    "file_path": "src/main.py",
    "line_number": 42,
    "error_message": "Missing parenthesis in function call",
    "suggested_fix": """def buggy_function():
    try:
        result = 1 / 0
        return result
    except ZeroDivisionError:
        print("Error: Division by zero is not allowed.")
        return None

# Call the function
buggy_function()""",
    "build_number": 1234,
    "timestamp": "2023-05-15 14:30:00"
}

    
    return render_template('summary.html', 
                         summary=summary_data,
                         fix_id=fix_id)

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

def evaluate_votes(fix_id):
    if fix_id not in fixes:
        print(f"[{fix_id}] Fix ID not found.")
        return

    fix = fixes[fix_id]
    total = len(fix["developers"])
    votes = fix["votes"]
    approvals = sum(1 for v in votes.values() if v == "approve")
    rejects = sum(1 for v in votes.values() if v == "reject")

    print(f"[{fix_id}] Evaluating votes: {approvals} approvals, {rejects} rejects out of {total} developers")

    if approvals > total / 2:
        print(f"[{fix_id}] Majority approved. Proceeding with fix (build #{fix['build_number']}).")
        # TODO: add logic to apply the fix

    elif rejects >= total / 2:  # If majority reject
        print(f"[{fix_id}] ❌ Majority rejected...Calling LLM again")
        # TODO: call to LLM
    else:
        print(f"[{fix_id}] No clear majority. Defaulting to rollback...")
        rollback_success = trigger_rollback()
        if rollback_success:
            send_rollback_notification(fix["developers"], fix["build_number"])

def send_rollback_notification(emails, build_number):
    subject = f"🚨 Rollback Initiated for Build #{build_number}"
    body = f"""
    The majority of developers rejected the proposed fix for Build #{build_number}.
    
    The system has automatically rolled back to the last stable build.
    
    Please investigate and submit a new fix when ready.
    """
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(emails)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, emails, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Failed to send rollback notification: {e}")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
