import requests
import os
from dotenv import load_dotenv
load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def get_developers_up_to_commit(repo, file_path, commit_sha):
   
    url = f"https://api.github.com/repos/{repo}/commits"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
    params = {"path": file_path, "sha": commit_sha, "per_page": 1}  # Fetch last 50 commits up to that SHA

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

def push_code_to_github(repo, file_path, new_content, commit_message):
    """
    Push new code content to a GitHub repository.
    
    Args:
        repo (str): GitHub repository in "owner/repo" format
        file_path (str): Path to the file in the repository
        new_content (str): New content for the file
        commit_message (str): Commit message
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get the current file SHA (needed for update)
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        
        # Get the reference to the main branch
        ref_url = f"https://api.github.com/repos/{repo}/git/refs/heads/main"
        ref_response = requests.get(ref_url, headers=headers)
        if ref_response.status_code != 200:
            print(f"Failed to get branch reference: {ref_response.json()}")
            return False
            
        commit_sha = ref_response.json()["object"]["sha"]
        
        # Get the current tree
        commit_url = f"https://api.github.com/repos/{repo}/git/commits/{commit_sha}"
        commit_response = requests.get(commit_url, headers=headers)
        if commit_response.status_code != 200:
            print(f"Failed to get commit: {commit_response.json()}")
            return False
            
        tree_sha = commit_response.json()["tree"]["sha"]
        
        # Create a new blob with the new content
        blob_url = f"https://api.github.com/repos/{repo}/git/blobs"
        blob_data = {
            "content": new_content,
            "encoding": "utf-8"
        }
        blob_response = requests.post(blob_url, headers=headers, json=blob_data)
        if blob_response.status_code != 201:
            print(f"Failed to create blob: {blob_response.json()}")
            return False
            
        new_blob_sha = blob_response.json()["sha"]
        
        # Create a new tree with the updated file
        tree_url = f"https://api.github.com/repos/{repo}/git/trees"
        tree_data = {
            "base_tree": tree_sha,
            "tree": [
                {
                    "path": file_path,
                    "mode": "100644",  # File mode (100644 is normal file)
                    "type": "blob",
                    "sha": new_blob_sha
                }
            ]
        }
        tree_response = requests.post(tree_url, headers=headers, json=tree_data)
        if tree_response.status_code != 201:
            print(f"Failed to create tree: {tree_response.json()}")
            return False
            
        new_tree_sha = tree_response.json()["sha"]
        
        # Create a new commit
        commit_url = f"https://api.github.com/repos/{repo}/git/commits"
        commit_data = {
            "message": commit_message,
            "parents": [commit_sha],
            "tree": new_tree_sha
        }
        commit_response = requests.post(commit_url, headers=headers, json=commit_data)
        if commit_response.status_code != 201:
            print(f"Failed to create commit: {commit_response.json()}")
            return False
            
        new_commit_sha = commit_response.json()["sha"]
        
        # Update the reference
        ref_url = f"https://api.github.com/repos/{repo}/git/refs/heads/main"
        ref_data = {
            "sha": new_commit_sha
        }
        ref_response = requests.patch(ref_url, headers=headers, json=ref_data)
        if ref_response.status_code != 200:
            print(f"Failed to update reference: {ref_response.json()}")
            return False
            
        return True
        
    except Exception as e:
        print(f"Error pushing code to GitHub: {str(e)}")
        return False