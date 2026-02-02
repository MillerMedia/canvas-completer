#!/usr/bin/env python3
"""
Canvas Assignment Fetcher - Browser Automation Version
Uses Playwright to handle Northwestern SSO authentication.
Supports headless sync when valid session cookies exist.
"""

import json
import re
import sys
import requests
from pathlib import Path
from datetime import datetime, timedelta
from html import unescape
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Configuration
CANVAS_BASE_URL = "https://canvas.northwestern.edu"
CONFIG_DIR = Path.home() / ".config" / "canvas-completer"
SESSION_FILE = CONFIG_DIR / "session.json"
DATA_DIR = CONFIG_DIR / "data" / "courses"


def save_session(context):
    """Save browser session/cookies for reuse."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    storage = context.storage_state()
    with open(SESSION_FILE, "w") as f:
        json.dump(storage, f)
    SESSION_FILE.chmod(0o600)
    print(f"Session saved to: {SESSION_FILE}")


def load_session():
    """Load saved session if it exists."""
    if SESSION_FILE.exists():
        return str(SESSION_FILE)
    return None


def clear_session():
    """Remove saved session."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        print("Session cleared.")
    else:
        print("No saved session found.")


class HeadlessCanvasAPI:
    """Headless Canvas API client using saved session cookies."""

    def __init__(self):
        self.session = requests.Session()
        self.authenticated = False
        self._load_cookies()

    def _load_cookies(self):
        """Load cookies from saved Playwright session."""
        if not SESSION_FILE.exists():
            return False

        try:
            with open(SESSION_FILE) as f:
                state = json.load(f)

            # Extract cookies from Playwright storage state
            for cookie in state.get("cookies", []):
                self.session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"),
                )

            return True
        except Exception as e:
            print(f"Could not load session: {e}")
            return False

    def verify_auth(self):
        """Verify the session is still valid."""
        try:
            response = self.session.get(
                f"{CANVAS_BASE_URL}/api/v1/users/self",
                timeout=10
            )
            if response.ok:
                self.authenticated = True
                return response.json()
            return None
        except:
            return None

    def get(self, endpoint):
        """Make a GET request to Canvas API."""
        url = f"{CANVAS_BASE_URL}{endpoint}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_raw(self, url):
        """Get raw content from a URL."""
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response


def try_headless_sync(days_ahead=14):
    """Try to sync without opening browser. Returns None if auth fails."""
    api = HeadlessCanvasAPI()

    user = api.verify_auth()
    if not user:
        return None  # Need browser login

    print("\n" + "=" * 60)
    print("Syncing Canvas Data (headless)")
    print("=" * 60)
    print(f"\nLogged in as: {user.get('name', 'Unknown')}")

    # Get courses
    print("\nFetching courses...")
    try:
        courses = api.get("/api/v1/courses?enrollment_state=active&per_page=50&include[]=syllabus_body&include[]=term")
    except Exception as e:
        print(f"Error fetching courses: {e}")
        return None

    print(f"Found {len(courses)} active course(s)")

    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)
    all_upcoming = []

    for course in courses:
        course_id = course.get("id")
        course_name = course.get("name", "Unknown Course")
        course_dir_name = sanitize_filename(course_name)
        course_dir = DATA_DIR / course_dir_name

        print(f"\n--- {course_name} ---")

        # Save course info and syllabus
        syllabus_html = course.get("syllabus_body", "")
        syllabus_md = html_to_markdown(syllabus_html)
        save_course_data(course, syllabus_md, course_dir)

        if syllabus_md:
            print(f"  ✓ Syllabus saved")
        else:
            print(f"  - No syllabus found")

        # Fetch assignments
        try:
            assignments = api.get(f"/api/v1/courses/{course_id}/assignments?per_page=100&include[]=rubric&include[]=submission")
        except Exception as e:
            print(f"  ✗ Could not fetch assignments: {e}")
            continue

        assignments_dir = course_dir / "assignments"
        upcoming_count = 0

        for assignment in assignments:
            due_at = assignment.get("due_at")
            is_upcoming = False

            if due_at:
                try:
                    due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                    if now.astimezone() <= due_date <= cutoff.astimezone():
                        is_upcoming = True
                        upcoming_count += 1
                except:
                    pass

            metadata = save_assignment_data(assignment, course_name, assignments_dir)

            if is_upcoming:
                all_upcoming.append({
                    "course": course_name,
                    "name": assignment.get("name"),
                    "due_at": due_date,
                    "points": assignment.get("points_possible"),
                    "url": assignment.get("html_url"),
                    "path": str(assignments_dir / sanitize_filename(assignment.get("name", "unknown"))),
                })

        print(f"  ✓ {len(assignments)} assignment(s) saved ({upcoming_count} upcoming)")

        # Fetch modules (headless version)
        try:
            modules = api.get(f"/api/v1/courses/{course_id}/modules?include[]=items&per_page=50")
            modules_dir = course_dir / "modules"
            modules_dir.mkdir(parents=True, exist_ok=True)

            for module in modules:
                module_name = module.get('name', 'Unknown Module')
                items = module.get('items', [])

                # Process each item
                processed_items = []
                for item in items:
                    if item.get('type') == 'Page':
                        page_url = item.get('url')
                        if page_url:
                            try:
                                page_data = api.get(page_url.replace(CANVAS_BASE_URL, ''))
                                item['body'] = page_data.get('body', '')
                            except:
                                pass
                    elif item.get('type') == 'File':
                        # Fetch file metadata to get download URL
                        file_url = item.get('url')
                        if file_url:
                            try:
                                file_data = api.get(file_url.replace(CANVAS_BASE_URL, ''))
                                item['download_url'] = file_data.get('url')
                                item['filename'] = file_data.get('filename')
                            except:
                                pass

                    from content_extractor import process_module_item
                    processed = process_module_item(item, api, course_dir / "files")
                    processed_items.append(processed)

                module['items'] = processed_items

                from content_extractor import save_module_content
                save_module_content(module, course_dir)

            if modules:
                print(f"  ✓ {len(modules)} module(s) processed")
        except Exception as e:
            print(f"  - Modules: {e}")

    # Sort and save
    all_upcoming.sort(key=lambda x: x["due_at"])

    summary_file = DATA_DIR / "upcoming_assignments.json"
    with open(summary_file, "w") as f:
        json.dump([{
            **a,
            "due_at": a["due_at"].isoformat()
        } for a in all_upcoming], f, indent=2)

    print(f"\n" + "=" * 60)
    print(f"Sync complete! Data saved to: {DATA_DIR}")
    print(f"=" * 60)

    return all_upcoming


def sanitize_filename(name):
    """Convert a string to a safe filename."""
    # Remove or replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name)
    name = name.strip('._')
    return name[:100]  # Limit length


def html_to_markdown(html):
    """Convert HTML to basic markdown."""
    if not html:
        return ""

    # Basic HTML to markdown conversions
    text = html

    # Headers
    text = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n', text, flags=re.DOTALL)
    text = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n', text, flags=re.DOTALL)
    text = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n', text, flags=re.DOTALL)
    text = re.sub(r'<h4[^>]*>(.*?)</h4>', r'#### \1\n', text, flags=re.DOTALL)

    # Bold and italic
    text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text, flags=re.DOTALL)
    text = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text, flags=re.DOTALL)
    text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', text, flags=re.DOTALL)

    # Links
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.DOTALL)

    # Lists
    text = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text, flags=re.DOTALL)
    text = re.sub(r'</?[ou]l[^>]*>', '\n', text)

    # Paragraphs and breaks
    text = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', text, flags=re.DOTALL)
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</?div[^>]*>', '\n', text)

    # Remove remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = unescape(text)

    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


def wait_for_canvas_login(page, timeout_minutes=5):
    """Wait for user to complete SSO login and reach Canvas dashboard."""
    print("\n" + "=" * 60)
    print("Canvas Login Required")
    print("=" * 60)
    print("""
A browser window has opened. Please:
  1. Complete the Northwestern SSO login
  2. Handle any 2FA prompts
  3. Wait until you see your Canvas dashboard

The script will automatically continue once you're logged in.
""")
    print(f"Waiting up to {timeout_minutes} minutes for login...")

    try:
        page.wait_for_url(f"{CANVAS_BASE_URL}/**", timeout=timeout_minutes * 60 * 1000)
        page.wait_for_selector(
            "#dashboard, .ic-Dashboard-header, .dashboard-header",
            timeout=30000
        )
        print("\nLogin successful!")
        return True
    except PlaywrightTimeout:
        print("\nLogin timed out. Please try again.")
        return False


def check_if_logged_in(page):
    """Check if we're already logged into Canvas."""
    try:
        page.goto(CANVAS_BASE_URL, timeout=15000)
        page.wait_for_load_state("networkidle", timeout=10000)

        if CANVAS_BASE_URL in page.url:
            dashboard = page.query_selector("#dashboard, .ic-Dashboard-header, .dashboard-header")
            if dashboard:
                return True
    except:
        pass
    return False


def fetch_user_info(page):
    """Get current user info."""
    response = page.request.get(f"{CANVAS_BASE_URL}/api/v1/users/self")
    if response.ok:
        return response.json()
    return None


def fetch_courses(page):
    """Get all active courses."""
    response = page.request.get(
        f"{CANVAS_BASE_URL}/api/v1/courses?enrollment_state=active&per_page=50&include[]=syllabus_body&include[]=term"
    )
    if response.ok:
        return response.json()
    return []


def fetch_assignment_details(page, course_id, assignment_id):
    """Fetch full assignment details including rubric."""
    response = page.request.get(
        f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/assignments/{assignment_id}?include[]=rubric&include[]=submission"
    )
    if response.ok:
        return response.json()
    return None


def fetch_course_modules(page, course_id):
    """Fetch course modules and items."""
    response = page.request.get(
        f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/modules?include[]=items&per_page=50"
    )
    if response.ok:
        return response.json()
    return []


def save_course_data(course, syllabus_md, course_dir):
    """Save course metadata and syllabus."""
    course_dir.mkdir(parents=True, exist_ok=True)

    # Save course info
    course_info = {
        "id": course.get("id"),
        "name": course.get("name"),
        "code": course.get("course_code"),
        "term": course.get("term", {}).get("name") if course.get("term") else None,
        "fetched_at": datetime.now().isoformat(),
    }

    with open(course_dir / "course_info.json", "w") as f:
        json.dump(course_info, f, indent=2)

    # Save syllabus
    if syllabus_md:
        with open(course_dir / "syllabus.md", "w") as f:
            f.write(f"# {course.get('name')} - Syllabus\n\n")
            f.write(syllabus_md)

    return course_info


def save_assignment_data(assignment, course_name, assignments_dir):
    """Save assignment metadata and requirements."""
    assignment_name = sanitize_filename(assignment.get("name", "unknown"))
    assignment_dir = assignments_dir / assignment_name
    assignment_dir.mkdir(parents=True, exist_ok=True)

    # Parse due date
    due_at = assignment.get("due_at")
    due_date = None
    if due_at:
        try:
            due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        except:
            pass

    # Extract submission info (nested in 'submission' object)
    submission = assignment.get("submission", {}) or {}
    workflow_state = submission.get("workflow_state", "unsubmitted")

    # Determine submission status
    has_submitted = workflow_state in ("submitted", "graded", "pending_review")
    is_graded = workflow_state == "graded"

    # Save assignment metadata
    metadata = {
        "id": assignment.get("id"),
        "name": assignment.get("name"),
        "course": course_name,
        "due_at": due_at,
        "due_at_formatted": due_date.strftime("%Y-%m-%d %H:%M %Z") if due_date else None,
        "points_possible": assignment.get("points_possible"),
        "submission_types": assignment.get("submission_types", []),
        "allowed_extensions": assignment.get("allowed_extensions", []),
        "url": assignment.get("html_url"),
        "has_submitted": has_submitted,
        "is_graded": is_graded,
        "workflow_state": workflow_state,
        "submitted_at": submission.get("submitted_at"),
        "score": submission.get("score"),
        "grade": submission.get("grade"),
        "fetched_at": datetime.now().isoformat(),
    }

    with open(assignment_dir / "assignment.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # Save requirements/description as markdown
    description_html = assignment.get("description", "")
    description_md = html_to_markdown(description_html)

    with open(assignment_dir / "requirements.md", "w") as f:
        f.write(f"# {assignment.get('name')}\n\n")
        f.write(f"**Course:** {course_name}\n")
        f.write(f"**Due:** {metadata['due_at_formatted'] or 'No due date'}\n")
        f.write(f"**Points:** {metadata['points_possible'] or 'Not specified'}\n")
        f.write(f"**Submission Type:** {', '.join(metadata['submission_types']) or 'Not specified'}\n")
        if metadata['allowed_extensions']:
            f.write(f"**Allowed File Types:** {', '.join(metadata['allowed_extensions'])}\n")
        f.write(f"\n---\n\n")
        f.write("## Assignment Description\n\n")
        f.write(description_md if description_md else "*No description provided*")
        f.write("\n")

    # Save rubric if available
    rubric = assignment.get("rubric")
    if rubric:
        with open(assignment_dir / "rubric.md", "w") as f:
            f.write(f"# Rubric: {assignment.get('name')}\n\n")
            f.write(f"**Total Points:** {assignment.get('points_possible', 'N/A')}\n\n")

            for criterion in rubric:
                f.write(f"## {criterion.get('description', 'Criterion')}\n")
                f.write(f"**Points:** {criterion.get('points', 'N/A')}\n\n")

                ratings = criterion.get("ratings", [])
                if ratings:
                    f.write("| Rating | Points | Description |\n")
                    f.write("|--------|--------|-------------|\n")
                    for rating in ratings:
                        desc = rating.get('long_description') or rating.get('description', '')
                        f.write(f"| {rating.get('description', '')} | {rating.get('points', '')} | {desc} |\n")
                    f.write("\n")

    return metadata


def sync_all_data(page, days_ahead=14):
    """Sync all course data, assignments, and syllabi."""
    print("\n" + "=" * 60)
    print("Syncing Canvas Data")
    print("=" * 60)

    # Get user info
    user = fetch_user_info(page)
    if user:
        print(f"\nLogged in as: {user.get('name', 'Unknown')}")

    # Get courses
    print("\nFetching courses...")
    courses = fetch_courses(page)
    print(f"Found {len(courses)} active course(s)")

    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)
    all_upcoming = []

    for course in courses:
        course_id = course.get("id")
        course_name = course.get("name", "Unknown Course")
        course_dir_name = sanitize_filename(course_name)
        course_dir = DATA_DIR / course_dir_name

        print(f"\n--- {course_name} ---")

        # Save course info and syllabus
        syllabus_html = course.get("syllabus_body", "")
        syllabus_md = html_to_markdown(syllabus_html)
        save_course_data(course, syllabus_md, course_dir)

        if syllabus_md:
            print(f"  ✓ Syllabus saved")
        else:
            print(f"  - No syllabus found")

        # Fetch assignments
        response = page.request.get(
            f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/assignments?per_page=100&include[]=rubric&include[]=submission"
        )

        if not response.ok:
            print(f"  ✗ Could not fetch assignments")
            continue

        assignments = response.json()
        assignments_dir = course_dir / "assignments"

        upcoming_count = 0
        for assignment in assignments:
            due_at = assignment.get("due_at")

            # Save all assignments, but track upcoming ones
            is_upcoming = False
            if due_at:
                try:
                    due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                    if now.astimezone() <= due_date <= cutoff.astimezone():
                        is_upcoming = True
                        upcoming_count += 1
                except:
                    pass

            metadata = save_assignment_data(assignment, course_name, assignments_dir)

            if is_upcoming:
                all_upcoming.append({
                    "course": course_name,
                    "name": assignment.get("name"),
                    "due_at": due_date,
                    "points": assignment.get("points_possible"),
                    "url": assignment.get("html_url"),
                    "path": str(assignments_dir / sanitize_filename(assignment.get("name", "unknown"))),
                })

        print(f"  ✓ {len(assignments)} assignment(s) saved ({upcoming_count} upcoming)")

        # Fetch and process module content
        try:
            from content_extractor import fetch_and_process_modules
            modules = fetch_and_process_modules(page, course_id, course_dir)
            if modules:
                print(f"  ✓ {len(modules)} module(s) processed")
        except Exception as e:
            print(f"  - Modules: {e}")

    # Sort upcoming by due date
    all_upcoming.sort(key=lambda x: x["due_at"])

    # Save summary of upcoming assignments
    summary_file = DATA_DIR / "upcoming_assignments.json"
    with open(summary_file, "w") as f:
        json.dump([{
            **a,
            "due_at": a["due_at"].isoformat()
        } for a in all_upcoming], f, indent=2)

    print(f"\n" + "=" * 60)
    print(f"Sync complete! Data saved to: {DATA_DIR}")
    print(f"=" * 60)

    return all_upcoming


def display_assignments(assignments):
    """Display assignments in a nice format."""
    if not assignments:
        print("\nNo upcoming assignments found!")
        return

    print(f"\nFound {len(assignments)} upcoming assignment(s):\n")
    for a in assignments:
        due_str = a["due_at"].strftime("%a %b %d, %I:%M %p")
        points = f"({a['points']} pts)" if a['points'] else ""
        print(f"  [{a['course']}]")
        print(f"    {a['name']} {points}")
        print(f"    Due: {due_str}")
        print(f"    Local: {a['path']}")
        print()


def show_data_location():
    """Show where data is stored."""
    print(f"\nData directory: {DATA_DIR}")
    if DATA_DIR.exists():
        print("\nCourses:")
        for course_dir in sorted(DATA_DIR.iterdir()):
            if course_dir.is_dir() and course_dir.name != ".DS_Store":
                print(f"  - {course_dir.name}/")
                assignments_dir = course_dir / "assignments"
                if assignments_dir.exists():
                    count = len([d for d in assignments_dir.iterdir() if d.is_dir()])
                    print(f"      ({count} assignments)")
    else:
        print("No data synced yet. Run 'python canvas_browser.py sync' first.")


def main():
    """Main entry point."""
    # Handle commands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "logout":
            clear_session()
            return 0
        elif cmd == "where":
            show_data_location()
            return 0
        elif cmd == "--help":
            print("Usage: python canvas_browser.py [command]")
            print("\nCommands:")
            print("  (none)    Show upcoming assignments (quick check)")
            print("  sync      Full sync - fetch all assignments, syllabi, rubrics")
            print("  where     Show where data is stored")
            print("  logout    Clear saved session")
            return 0

    do_full_sync = len(sys.argv) > 1 and sys.argv[1] == "sync"

    print("Starting Canvas browser automation...\n")

    with sync_playwright() as p:
        session_path = load_session()
        browser = p.chromium.launch(headless=False)

        if session_path:
            print("Loading saved session...")
            try:
                context = browser.new_context(storage_state=session_path)
            except Exception as e:
                print(f"Could not load saved session: {e}")
                context = browser.new_context()
        else:
            context = browser.new_context()

        page = context.new_page()
        logged_in = check_if_logged_in(page)

        if not logged_in:
            page.goto(CANVAS_BASE_URL)
            if not wait_for_canvas_login(page):
                browser.close()
                return 1
            save_session(context)
        else:
            print("Using saved session - already logged in!")

        if do_full_sync:
            # Full sync mode
            assignments = sync_all_data(page, days_ahead=14)
            display_assignments(assignments)
        else:
            # Quick mode - just show upcoming
            print("\nFetching upcoming assignments...")
            print("(Run 'python canvas_browser.py sync' for full data fetch)\n")

            user = fetch_user_info(page)
            if user:
                print(f"Logged in as: {user.get('name', 'Unknown')}\n")

            courses = fetch_courses(page)
            now = datetime.now()
            cutoff = now + timedelta(days=7)
            all_assignments = []

            for course in courses:
                course_id = course.get("id")
                course_name = course.get("name", "Unknown Course")

                response = page.request.get(
                    f"{CANVAS_BASE_URL}/api/v1/courses/{course_id}/assignments?per_page=100&bucket=upcoming"
                )

                if not response.ok:
                    continue

                for assignment in response.json():
                    due_at = assignment.get("due_at")
                    if due_at:
                        try:
                            due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                            if now.astimezone() <= due_date <= cutoff.astimezone():
                                all_assignments.append({
                                    "course": course_name,
                                    "name": assignment.get("name"),
                                    "due_at": due_date,
                                    "points": assignment.get("points_possible"),
                                    "url": assignment.get("html_url"),
                                    "path": "Run 'sync' to save locally",
                                })
                        except:
                            continue

            all_assignments.sort(key=lambda x: x["due_at"])

            if not all_assignments:
                print("No upcoming assignments in the next 7 days!")
            else:
                print(f"Found {len(all_assignments)} upcoming assignment(s):\n")
                for a in all_assignments:
                    due_str = a["due_at"].strftime("%a %b %d, %I:%M %p")
                    points = f"({a['points']} pts)" if a['points'] else ""
                    print(f"  [{a['course']}]")
                    print(f"    {a['name']} {points}")
                    print(f"    Due: {due_str}")
                    print()

        browser.close()

    return 0


if __name__ == "__main__":
    exit(main())
