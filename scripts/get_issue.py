import json
import os
import sys
import ssl
import urllib.request


def main():
    if len(sys.argv) < 2:
        print("Usage: get_issue.py <number> [<owner/repo>]")
        sys.exit(1)
    num = sys.argv[1]
    repo = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("REPO", "LeeHunter/anki-slicer")
    url = f"https://api.github.com/repos/{repo}/issues/{num}"
    ctx = ssl._create_unverified_context() if os.environ.get("INSECURE") else None
    with urllib.request.urlopen(url, context=ctx) as r:
        data = json.load(r)
    print(f"#{data.get('number')} {data.get('title')}")
    print()
    print(data.get('body') or "(no description)")


if __name__ == "__main__":
    main()

