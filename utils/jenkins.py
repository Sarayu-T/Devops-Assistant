import requests
import os
from dotenv import load_dotenv

load_dotenv()

JENKINS_URL = os.getenv("JENKINS_URL")
JOB_NAME = "github int"
JENKINS_USER = os.getenv("JENKINS_USER")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN")

def get_latest_failed_build():
    api_url = f"{JENKINS_URL}/job/{JOB_NAME}/api/json?tree=builds[number,result]"
    response = requests.get(api_url, auth=(JENKINS_USER, JENKINS_TOKEN))
    response.raise_for_status()

    for build in response.json().get("builds", []):
        if build["result"] == "FAILURE":
            return build["number"]
    return None

def get_full_console_log(build_number):
    log_url = f"{JENKINS_URL}/job/{JOB_NAME}/{build_number}/consoleText"
    response = requests.get(log_url, auth=(JENKINS_USER, JENKINS_TOKEN))

    if response.status_code != 200:
        return f"❌ Error fetching logs: {response.text}"

    return response.text 

def get_github_repo_and_sha(build_number):

    build_number = 2 # Hardcoded for testing TODO:  Remove this line
    api_url = f"{JENKINS_URL}/job/{JOB_NAME}/{build_number}/api/json"
    response = requests.get(api_url, auth=(JENKINS_USER, JENKINS_TOKEN))
    response.raise_for_status()
    
    data = response.json()
    git_url = None
    commit_sha = None

    for action in data.get("actions", []):
        if "remoteUrls" in action:
            git_url = action["remoteUrls"][0]
            git_url = git_url.replace(".git", "").split("github.com/")[1]
        if "lastBuiltRevision" in action:
            commit_sha = action["lastBuiltRevision"]["SHA1"]

    return git_url, commit_sha

def trigger_rollback():
    # TODO: fetch latest stable build
    url = "link_to_latest_stable_build"
    response = requests.post(url, auth=("jenkins_user", "jenkins_token"))
    if response.ok:
        print("Rollback triggered successfully")
    else:
        print(f"Rollback failed: {response.status_code} - {response.text}")

