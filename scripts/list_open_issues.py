import json
import os
import sys
import urllib.request
import ssl


def main():
    repo = os.environ.get("REPO", "LeeHunter/anki-slicer")
    url = f"https://api.github.com/repos/{repo}/issues?state=open&per_page=50"
    ctx = None
    if os.environ.get("INSECURE"):
        ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(url, context=ctx) as r:
            data = json.load(r)
    except Exception as e:
        print(f"ERROR: failed to fetch issues: {e}")
        sys.exit(2)

    # Filter out PRs (which have a 'pull_request' key)
    issues = [i for i in data if "pull_request" not in i]

    for i in issues:
        num = i.get("number")
        title = i.get("title", "")
        state = i.get("state")
        created = i.get("created_at")
        user = (i.get("user") or {}).get("login")
        labels = ",".join(l.get("name") for l in i.get("labels", []))
        url = i.get("html_url")
        print(f"#{num} [{state}] {title}")
        print(f"  by {user} on {created}  labels: {labels}")
        print(f"  {url}\n")


if __name__ == "__main__":
    main()
