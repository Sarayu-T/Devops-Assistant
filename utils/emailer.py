import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
FLASK_BASE_URL = os.getenv("FLASK_BASE_URL", "http://localhost:5000")

def send_email(recipients, file_path, build_number, fix_id):
    if not recipients:
        return "No developers found, skipping email notification."

    for email in recipients:
        approve_url = f"{FLASK_BASE_URL}/vote?fix_id={fix_id}&email={email}&vote=approve"
        reject_url = f"{FLASK_BASE_URL}/vote?fix_id={fix_id}&email={email}&vote=reject"
        summary_url = f"{FLASK_BASE_URL}/summary?fix_id={fix_id}"  # New summary link

        subject = f"🚨 Jenkins Build #{build_number} Failed: Issue in {file_path}"
        body = f"""
        The latest Jenkins pipeline run (Build #{build_number}) failed due to an issue in {file_path}.

        Please review and vote on the suggested fix:

        ✅ Approve: {approve_url}
        ❌ Reject: {reject_url}

        View detailed error summary: {summary_url}

        This link will expire in 1 hour.
        """

        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, email, msg.as_string())
            server.quit()
        except Exception as e:
            print(f"Failed to send email to {email}: {e}")

    return "Emails sent to all recipients."