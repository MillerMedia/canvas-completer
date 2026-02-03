#!/usr/bin/env python3
"""
Canvas Assignment Fetcher
Retrieves upcoming homework assignments from Canvas LMS.
"""

import os
import sys
import json
import webbrowser
import requests
from pathlib import Path
from datetime import datetime, timedelta
from getpass import getpass

# Configuration
CONFIG_DIR = Path.home() / ".config" / "canvas-completer"
CONFIG_FILE = CONFIG_DIR / "config.json"

def get_canvas_url():
    """Get Canvas URL from config or prompt user."""
    config = load_config()
    if "canvas_url" in config:
        return config["canvas_url"]
    return None

def get_api_url():
    """Get Canvas API URL."""
    canvas_url = get_canvas_url()
    if canvas_url:
        return f"{canvas_url}/api/v1"
    return None


def load_config():
    """Load configuration from file."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config):
    """Save configuration to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    # Set restrictive permissions (owner read/write only)
    CONFIG_FILE.chmod(0o600)


def setup_canvas_url():
    """Prompt user for their Canvas instance URL."""
    print("\n" + "=" * 60)
    print("Canvas Instance Setup")
    print("=" * 60)
    print("""
Please enter your school's Canvas URL.

Examples:
  - https://canvas.instructure.com
  - https://canvas.university.edu
  - https://school.instructure.com

This is the URL you use to access Canvas in your browser.
""")

    while True:
        url = input("Canvas URL: ").strip()

        # Clean up URL
        if not url.startswith("http"):
            url = "https://" + url
        url = url.rstrip("/")

        # Basic validation
        if not url or "." not in url:
            print("Please enter a valid URL.")
            continue

        # Confirm
        print(f"\nUsing: {url}")
        confirm = input("Is this correct? (y/n): ").strip().lower()
        if confirm in ("y", "yes", ""):
            return url
        print()


def get_token_interactive():
    """Guide user through token generation with browser."""
    canvas_url = get_canvas_url()

    print("\n" + "=" * 60)
    print("Canvas Authentication Setup")
    print("=" * 60)
    print("""
To connect to Canvas, you need to generate a personal access token.

I'll open your browser to the Canvas settings page where you can create one.

Steps:
  1. Log in to Canvas if prompted
  2. Scroll down to "Approved Integrations"
  3. Click "+ New Access Token"
  4. Enter a purpose like "Assignment Automation"
  5. Click "Generate Token"
  6. Copy the token (you'll only see it once!)
  7. Come back here and paste it
""")

    input("Press Enter to open Canvas in your browser...")

    # Open browser to Canvas settings page
    settings_url = f"{canvas_url}/profile/settings"
    print(f"\nOpening: {settings_url}")
    webbrowser.open(settings_url)

    print("\n" + "-" * 60)
    print("After you've generated your token, paste it below.")
    print("(The token will be hidden as you type for security)")
    print("-" * 60 + "\n")

    # Use getpass to hide the token as they type
    token = getpass("Paste your Canvas token: ").strip()

    if not token:
        print("No token provided. Exiting.")
        return None

    return token


def verify_token(token):
    """Verify the token works by fetching user info."""
    api_url = get_api_url()
    if not api_url:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get(f"{api_url}/users/self", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError:
        return None


def authenticate():
    """Authenticate with Canvas, using stored token or prompting for new one."""
    config = load_config()

    # Ensure Canvas URL is configured
    if not config.get("canvas_url"):
        canvas_url = setup_canvas_url()
        config["canvas_url"] = canvas_url
        save_config(config)

    token = config.get("token")

    # If we have a stored token, verify it still works
    if token:
        print("Found stored credentials, verifying...")
        user = verify_token(token)
        if user:
            print(f"Authenticated as: {user.get('name', 'Unknown')}")
            return token
        else:
            print("Stored token is invalid or expired.")
            token = None

    # Need to get a new token
    token = get_token_interactive()
    if not token:
        return None

    # Verify the new token
    print("\nVerifying token...")
    user = verify_token(token)

    if not user:
        print("Token verification failed. Please check that you copied it correctly.")
        return None

    print(f"Success! Authenticated as: {user.get('name', 'Unknown')}")

    # Save the token
    config["token"] = token
    config["user_name"] = user.get("name")
    config["user_id"] = user.get("id")
    save_config(config)
    print(f"Token saved to: {CONFIG_FILE}")

    return token


def make_request(endpoint, token):
    """Make an authenticated request to Canvas API."""
    api_url = get_api_url()
    if not api_url:
        raise Exception("Canvas URL not configured")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{api_url}{endpoint}", headers=headers)
    response.raise_for_status()
    return response.json()


def get_courses(token):
    """Get all active courses for the current user."""
    courses = make_request("/courses?enrollment_state=active&per_page=50", token)
    return courses


def get_assignments(token, course_id, upcoming_only=True):
    """Get assignments for a specific course."""
    endpoint = f"/courses/{course_id}/assignments?per_page=100"
    if upcoming_only:
        endpoint += "&bucket=upcoming"
    assignments = make_request(endpoint, token)
    return assignments


def get_upcoming_assignments(token, days_ahead=7):
    """Get all upcoming assignments across all courses."""
    courses = get_courses(token)
    all_assignments = []

    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)

    for course in courses:
        course_id = course.get("id")
        course_name = course.get("name", "Unknown Course")

        try:
            assignments = get_assignments(token, course_id)
            for assignment in assignments:
                due_at = assignment.get("due_at")
                if due_at:
                    due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                    if now.astimezone() <= due_date <= cutoff.astimezone():
                        all_assignments.append({
                            "course": course_name,
                            "name": assignment.get("name"),
                            "due_at": due_date,
                            "points": assignment.get("points_possible"),
                            "url": assignment.get("html_url"),
                        })
        except requests.exceptions.HTTPError as e:
            print(f"Warning: Could not fetch assignments for {course_name}: {e}")

    # Sort by due date
    all_assignments.sort(key=lambda x: x["due_at"])
    return all_assignments


def logout():
    """Remove stored credentials."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        print("Logged out. Credentials removed.")
    else:
        print("No stored credentials found.")


def main():
    """Main entry point."""
    # Handle logout command
    if len(sys.argv) > 1 and sys.argv[1] == "logout":
        logout()
        return 0

    # Authenticate (interactive if needed)
    token = authenticate()
    if not token:
        return 1

    print()

    # Fetch upcoming assignments
    print("Fetching assignments due in the next 7 days...\n")

    try:
        assignments = get_upcoming_assignments(token, days_ahead=7)
    except requests.exceptions.HTTPError as e:
        print(f"Error fetching assignments: {e}")
        return 1

    if not assignments:
        print("No upcoming assignments found!")
    else:
        print(f"Found {len(assignments)} upcoming assignment(s):\n")
        for a in assignments:
            due_str = a["due_at"].strftime("%a %b %d, %I:%M %p")
            points = f"({a['points']} pts)" if a['points'] else ""
            print(f"  [{a['course']}]")
            print(f"    {a['name']} {points}")
            print(f"    Due: {due_str}")
            print(f"    {a['url']}\n")

    return 0


if __name__ == "__main__":
    exit(main())
