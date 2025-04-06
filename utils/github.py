import requests
import os
from dotenv import load_dotenv
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def get_developers_up_to_commit(repo, file_path, commit_sha):
   
    url = f"https://api.github.com/repos/{repo}/commits"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    params = {"path": file_path, "sha": commit_sha, "per_page": 50}  # Fetch last 50 commits up to that SHA

    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        print(f"❌ GitHub API Error: {response.json()}")
        return []

    commits = response.json()
    developers = set()

    for commit in commits:
        try:
            author = commit["commit"]["author"]
            developers.add(f"{author['name']} <{author['email']}>")
        except KeyError:
            continue  # Skip commits without valid author data

    return list(developers)