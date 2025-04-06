import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

def send_email(recipients, file_path, build_number):
    if not recipients:
        return "No developers found, skipping email notification."

    subject = f"🚨 Jenkins Build #{build_number} Failed: Issue in {file_path}"
    body = f"The latest Jenkins pipeline run (Build #{build_number}) has failed due to an issue in {file_path}."

    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, recipients, msg.as_string())
        server.quit()
        return "Email notification sent successfully!"
    except Exception as e:
        return f"Failed to send email: {e}"
