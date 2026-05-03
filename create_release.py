#!/usr/bin/env python3
"""Create GitHub release with binary attachment."""
import os
import sys

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system("/usr/bin/python3 -m pip install -q requests")
    import requests

owner = "jonathanvineet"
repo = "scrapee"
tag = "v3.0.0"
binary_path = "dist/scrapee"

# Get token
token = os.environ.get('GITHUB_TOKEN')
if not token:
    print("⚠️  GITHUB_TOKEN not in environment.")
    print("\nManual steps:")
    print("1. Open: https://github.com/jonathanvineet/scrapee/releases/new")
    print("2. Tag: v3.0.0")
    print("3. Title: Scrapee v3.0.0")
    print("4. Upload: dist/scrapee")
    print("5. Publish")
    sys.exit(0)

# Create release
url = f"https://api.github.com/repos/{owner}/{repo}/releases"
headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github+json"
}

release_data = {
    "tag_name": tag,
    "name": "Scrapee v3.0.0",
    "body": "🦇 Boot System + Project Detection\n\n✅ Production-ready\nSee README.md for installation and usage.",
    "draft": False,
    "prerelease": False
}

print("Creating release...")
resp = requests.post(url, json=release_data, headers=headers)
if resp.status_code == 409:
    print("✓ Release already exists")
    release_id = resp.json().get('id') or tag
elif resp.status_code == 201:
    release_id = resp.json()['id']
    print(f"✓ Release created (ID: {release_id})")
else:
    print(f"❌ Failed: {resp.status_code}")
    print(resp.text)
    sys.exit(1)

# Find existing upload URL
list_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
resp = requests.get(list_url, headers=headers)
if resp.status_code == 200:
    release = resp.json()
    release_id = release['id']
    
    # Check if binary already uploaded
    for asset in release.get('assets', []):
        if asset['name'] == 'scrapee':
            print(f"✓ Binary already uploaded: {asset['name']}")
            print(f"✓ Release ready: {release['html_url']}")
            sys.exit(0)
    
    # Upload binary
    print(f"Uploading binary...")
    upload_url = f"https://uploads.github.com/repos/{owner}/{repo}/releases/{release_id}/assets"
    with open(binary_path, 'rb') as f:
        binary_data = f.read()
        resp = requests.post(
            upload_url,
            headers={
                **headers,
                "Content-Type": "application/octet-stream"
            },
            params={"name": "scrapee"},
            data=binary_data
        )
    
    if resp.status_code == 201:
        asset = resp.json()
        size_mb = asset['size'] / (1024 * 1024)
        print(f"✓ Binary uploaded: {asset['name']} ({size_mb:.1f}M)")
    else:
        print(f"❌ Upload failed: {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    
    print(f"\n✅ Release ready: {release['html_url']}")
