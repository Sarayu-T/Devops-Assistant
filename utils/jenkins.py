import requests
import os
from dotenv import load_dotenv
import jenkins
import subprocess
import re

load_dotenv()

JENKINS_URL = os.getenv("JENKINS_URL")
JOB_NAME = os.getenv("JOB_NAME")
JENKINS_USER = os.getenv("JENKINS_USER")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN")


def get_jenkins_server():
    return jenkins.Jenkins(JENKINS_URL, username=JENKINS_USER, password=JENKINS_TOKEN)


def get_latest_failed_build():
    try:
        api_url = f"{JENKINS_URL}/job/{JOB_NAME}/api/json?tree=builds[number,result]"
        response = requests.get(api_url, auth=(JENKINS_USER, JENKINS_TOKEN))
        response.raise_for_status()

        for build in response.json().get("builds", []):
            if build["result"] == "FAILURE":
                print(build["number"])
                return build["number"]
        return None

    except requests.exceptions.HTTPError as e:
        print(f"Jenkins API error: {e}")
        print(f"Response content: {e.response.text}")
        return None


def get_latest_stable_build():
    try:
        api_url = f"{JENKINS_URL}/job/{JOB_NAME}/api/json?tree=builds[number,result]"
        response = requests.get(api_url, auth=(JENKINS_USER, JENKINS_TOKEN))
        response.raise_for_status()

        builds = response.json().get("builds", [])
        builds.sort(key=lambda b: b["number"], reverse=True)

        for build in builds:
            if build["result"] == "SUCCESS":
                return build["number"]
        return None

    except requests.exceptions.HTTPError as e:
        print(f"Jenkins API error: {e}")
        print(f"Response content: {e.response.text}")
        return None


def get_full_console_log(build_number):
    log_url = f"{JENKINS_URL}/job/{JOB_NAME}/{build_number}/consoleText"
    response = requests.get(log_url, auth=(JENKINS_USER, JENKINS_TOKEN))

    if response.status_code != 200:
        return f"❌ Error fetching logs: {response.text}"
    
    lines = response.text.splitlines()

    
    error_keywords = re.compile(
        r'(FAILURE:|error:|Traceback \(most recent call last\):|Exception|Build failed|command returned exit code [^0])',
        re.IGNORECASE
    )

    start_index = None
    for i, line in enumerate(lines):
        if error_keywords.search(line):
            start_index = i
            break

    if start_index is None:
        return response.text

    print("----------------------------------ERROR----------------------------------------------")
    print(lines[start_index:])
    return "\n".join(lines[start_index:])



def get_github_repo_and_sha(build_number):
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


def extract_commit_hash(build_info):
    # First, look for the "GIT_COMMIT" parameter in the actions
    for action in build_info.get("actions", []):
        for param in action.get("parameters", []):
            if param.get("name") == "GIT_COMMIT":
                return param.get("value")
    
    # If "GIT_COMMIT" is not found, check the "lastBuiltRevision" or "buildsByBranchName" for the SHA1
    for action in build_info.get("actions", []):
        if "lastBuiltRevision" in action:
            sha = action["lastBuiltRevision"].get("SHA1")
            if sha:
                return sha
        if "buildsByBranchName" in action:
            for branch in action["buildsByBranchName"].values():
                sha = branch.get("revision", {}).get("SHA1")
                if sha:
                    return sha
    
    # If no SHA1 found, check the changeset for a "commitId"
    changes = build_info.get("changeSet", {}).get("items", [])
    if changes and "commitId" in changes[0]:
        return changes[0]["commitId"]

    # Return None if no commit hash or "GIT_COMMIT" was found
    return None



def get_crumb():
    try:
        crumb_url = f"{JENKINS_URL}/crumbIssuer/api/json"
        response = requests.get(crumb_url, auth=(JENKINS_USER, JENKINS_TOKEN))
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Failed to get crumb: {str(e)}")
        return None


def git_rollback(commit_hash, repo_path=None):
    try:
        if repo_path:
            os.chdir(repo_path)

        subprocess.run(['git', 'fetch', 'origin'], check=True)
        subprocess.run(['git', 'checkout', commit_hash], check=True)

        current_branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True
        ).stdout.strip()

        subprocess.run(['git', 'push', 'origin', current_branch, '--force'], check=True)

        print(f"✅ Successfully rolled back GitHub repository to commit: {commit_hash}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Git rollback failed: {str(e)}")
        print(f"Command output: {e.output}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during Git rollback: {str(e)}")
        return False


def trigger_rollback(github_repo_path=None):
    stable_build = get_latest_stable_build()
    print("Stable build no.", stable_build)

    if not stable_build:
        print("No stable build found for rollback")
        return False

    try:
        build_info_url = f"{JENKINS_URL}/job/{JOB_NAME}/{stable_build}/api/json"
        print(f"🔍 Fetching build info from: {build_info_url}")
        build_info = requests.get(
            build_info_url,
            auth=(JENKINS_USER, JENKINS_TOKEN),
            timeout=10
        ).json()

        commit_hash = extract_commit_hash(build_info)
        if not commit_hash:
            print("❌ Could not fetch original Git commit")
            return False

        if github_repo_path:
            if not git_rollback(commit_hash, github_repo_path):
                print("❌ GitHub rollback failed, aborting Jenkins rollback")
                return False
        print("commit hash:", commit_hash)
        crumb = get_crumb()
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if crumb:
            headers[crumb['crumbRequestField']] = crumb['crumb']

        build_url = f"{JENKINS_URL}/job/{JOB_NAME}/buildWithParameters"
        params = {'GIT_COMMIT': commit_hash}

        response = requests.post(
            build_url,
            auth=(JENKINS_USER, JENKINS_TOKEN),
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code in [200, 201, 302]:
            print(f"✅ Rollback triggered (Build using commit: {commit_hash})")
            return True
        else:
            print(f"❌ Failed to trigger rollback (HTTP {response.status_code})")
            print(f"Jenkins Error: {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return False
