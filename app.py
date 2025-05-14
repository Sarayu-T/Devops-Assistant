from flask import Flask, request, jsonify,render_template
from threading import Timer
from datetime import datetime
import time
import uuid
import os
from dotenv import load_dotenv
from utils.rag_resolver import GitHubErrorResolver
from utils.jenkins import get_latest_failed_build, get_github_repo_and_sha, get_full_console_log, trigger_rollback
from utils.github import get_developers_up_to_commit, push_code_to_github
from utils.emailer import send_email
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
import json

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
resolver = GitHubErrorResolver(deepseek_api_key=DEEPSEEK_API_KEY)


EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

app = Flask(__name__)


fixes = {} # TODO: add db instead


@app.route("/webhook/jenkins", methods=["POST"])
def jenkins_webhook():
    #TODO: add security check by posting some secret token
    return trigger_alert()  # reuse your existing logic

   
def normalize_path(path):
    return path.replace("\\", "/")

def parse_llm_response(raw_response):
    if isinstance(raw_response, dict):
        return raw_response

    # Try to extract JSON inside a ```json ... ``` code block
    match = re.search(r"```json\s*(\{.*?\})\s*```", raw_response, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON decoding failed: {e}")
            return None
    else:
        print("⚠️ No JSON block found in response.")
        return None
def extract_code_blocks(text: str) -> list:
   
    match = re.search(r"```(?:[\w+-]*)?\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else ""

def trigger_alert():
    latest_failed_build = get_latest_failed_build()
    if not latest_failed_build:
        return jsonify({"error": "No failed builds found."}), 404
    print(latest_failed_build)
    github_repo, commit_sha = get_github_repo_and_sha(latest_failed_build)
    if not github_repo:
        return jsonify({"error": "Failed to determine GitHub repository."}), 500
    console_log = get_full_console_log(latest_failed_build)
    resolver.process_repository(github_repo)
    FAILED_FILE_PATH = normalize_path(resolver.get_failed_path(console_log))
    developers = get_developers_up_to_commit(github_repo, FAILED_FILE_PATH, commit_sha)
    emails = [dev.split("<")[1].strip(" >") for dev in developers if "<" in dev]
    
    console_log = get_full_console_log(latest_failed_build)

    
    raw_response = resolver.resolve_error(console_log)
    fix_info = raw_response
    fix_info = parse_llm_response(raw_response)
    print("-----------------------------------PARSED FIX INFO-----------------------------------")
    #print(fix_info)
    #fix_info["suggested_fix"] = extract_code_blocks(fix_info["suggested_fix"])


    fix_id = str(uuid.uuid4())
    fixes[fix_id] = {
    "developers": emails,
    "votes": {},
    "file_path": FAILED_FILE_PATH,
    "build_number": latest_failed_build,
    "start_time": time.time(),
    "suggested_fix": fix_info["suggested_fix"],
    "error_type": fix_info.get("error_type", "UnknownError"),
    "error_message": fix_info.get("error_message", "No error message"),
    "line_number": fix_info.get("line_number", "N/A")
    }

    email_status = send_email(emails, FAILED_FILE_PATH, latest_failed_build, fix_id)
    

    

    # print(suggested_fix)
    # Start 1hr countdown timer to evaluate votes
    Timer(60, evaluate_votes, args=(fix_id,)).start()



    return jsonify({
        "fix_id": fix_id,
        "file_path": FAILED_FILE_PATH,
        "build": latest_failed_build,
        "repo": github_repo,
        "developers": developers,
        "email_status": email_status,
        "console_log": console_log,
        "suggested_fix": fix_info["suggested_fix"]
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
    fix = fixes[fix_id]
    summary_data = {
        "error_type": fix.get("error_type", "UnknownError"),
        "file_path": fix["file_path"],
        "line_number": fix.get("line_number", "N/A"),
        "error_message": fix.get("error_message", "No error message"),
        "suggested_fix": fix["suggested_fix"],
        "build_number": fix["build_number"],
        "timestamp": datetime.fromtimestamp(fix["start_time"]).strftime("%Y-%m-%d %H:%M:%S")
    }

    
    return render_template('summary.html', 
                         summary=summary_data,
                         fix_id=fix_id)


def evaluate_votes(fix_id, attempt=0):
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
        print("-------------------------------SUGGESTED FIX-------------------------\n",fix["suggested_fix"])
        # Push the approved code to GitHub
        if 'suggested_fix' in fix:
            github_repo, _ = get_github_repo_and_sha(fix["build_number"])
            success = push_code_to_github(
                repo=github_repo,
                file_path=fix["file_path"],
                new_content=fix["suggested_fix"],
                commit_message=f"Auto-fix for build #{fix['build_number']} (approved by majority)"
            )
            if success:
                print(f"[{fix_id}] ✅ Code successfully pushed to GitHub")
            else:
                print(f"[{fix_id}] ❌ Failed to push code to GitHub")
        else:
            print(f"[{fix_id}] No suggested fix available to push")

    elif rejects >= total / 2 and attempt < 3:
        print(f"[{fix_id}] ❌ Rejected. Asking LLM for new fix (attempt {attempt + 1})")

        # LLM logic
        github_repo, _ = get_github_repo_and_sha(fix["build_number"])
        console_log = get_full_console_log(fix["build_number"])
        new_fix = resolver.resolve_error(console_log)

        # Reset votes
        fix["votes"] = {}
        send_email(fix["developers"], fix["file_path"], fix["build_number"], fix_id)

        # Schedule next evaluation
        Timer(60, evaluate_votes, args=(fix_id, attempt + 1)).start()

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
