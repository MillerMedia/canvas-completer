#!/usr/bin/env python3
"""
Canvas Completer - Interactive CLI
An autonomous homework assistant for Canvas LMS.
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown
from rich.status import Status
from rich import box

# Import our canvas browser module
import canvas_browser as canvas

console = Console()

# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "canvas-completer"
DATA_DIR = CONFIG_DIR / "data" / "courses"
SESSION_FILE = CONFIG_DIR / "session.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


def load_settings():
    """Load user settings."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {}


def save_settings(settings):
    """Save user settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def get_sync_status():
    """Get sync status for all courses."""
    courses = []

    if not DATA_DIR.exists():
        return courses

    for course_dir in sorted(DATA_DIR.iterdir()):
        if not course_dir.is_dir() or course_dir.name.startswith('.'):
            continue

        course_info_file = course_dir / "course_info.json"
        if not course_info_file.exists():
            continue

        with open(course_info_file) as f:
            info = json.load(f)

        # Count assignments
        assignments_dir = course_dir / "assignments"
        assignment_count = 0
        upcoming_count = 0

        if assignments_dir.exists():
            now = datetime.now().astimezone()
            cutoff = now + timedelta(days=14)

            for a_dir in assignments_dir.iterdir():
                if a_dir.is_dir():
                    assignment_count += 1
                    a_file = a_dir / "assignment.json"
                    if a_file.exists():
                        with open(a_file) as f:
                            a_info = json.load(f)
                        due_at = a_info.get("due_at")
                        if due_at:
                            try:
                                due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                                if now <= due_date <= cutoff:
                                    upcoming_count += 1
                            except:
                                pass

        # Parse last sync time
        fetched_at = info.get("fetched_at")
        if fetched_at:
            try:
                sync_time = datetime.fromisoformat(fetched_at)
                time_ago = datetime.now() - sync_time
                if time_ago.days > 0:
                    sync_str = f"{time_ago.days}d ago"
                elif time_ago.seconds > 3600:
                    sync_str = f"{time_ago.seconds // 3600}h ago"
                else:
                    sync_str = f"{time_ago.seconds // 60}m ago"
            except:
                sync_str = "Unknown"
        else:
            sync_str = "Never"

        courses.append({
            "name": info.get("name", course_dir.name),
            "code": info.get("code"),
            "term": info.get("term"),
            "path": course_dir,
            "assignment_count": assignment_count,
            "upcoming_count": upcoming_count,
            "last_sync": sync_str,
            "has_syllabus": (course_dir / "syllabus.md").exists(),
        })

    return courses


def get_upcoming_assignments(days=14):
    """Get all upcoming assignments across all courses."""
    assignments = []

    if not DATA_DIR.exists():
        return assignments

    now = datetime.now().astimezone()
    cutoff = now + timedelta(days=days)

    for course_dir in DATA_DIR.iterdir():
        if not course_dir.is_dir() or course_dir.name.startswith('.'):
            continue

        course_info_file = course_dir / "course_info.json"
        if course_info_file.exists():
            with open(course_info_file) as f:
                course_info = json.load(f)
            course_name = course_info.get("name", course_dir.name)
        else:
            course_name = course_dir.name

        assignments_dir = course_dir / "assignments"
        if not assignments_dir.exists():
            continue

        for a_dir in assignments_dir.iterdir():
            if not a_dir.is_dir():
                continue

            a_file = a_dir / "assignment.json"
            if not a_file.exists():
                continue

            with open(a_file) as f:
                a_info = json.load(f)

            due_at = a_info.get("due_at")
            if not due_at:
                continue

            try:
                due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                if now <= due_date <= cutoff:
                    assignments.append({
                        "name": a_info.get("name"),
                        "course": course_name,
                        "due_at": due_date,
                        "points": a_info.get("points_possible"),
                        "path": a_dir,
                        "submitted": a_info.get("has_submitted", False),
                        "is_graded": a_info.get("is_graded", False),
                        "score": a_info.get("score"),
                        "grade": a_info.get("grade"),
                        "workflow_state": a_info.get("workflow_state", "unsubmitted"),
                    })
            except:
                continue

    assignments.sort(key=lambda x: x["due_at"])
    return assignments


def is_authenticated():
    """Check if we have a saved session."""
    return SESSION_FILE.exists()


VERSION = "0.1.0"

def show_welcome():
    """Show welcome banner with rubber duck mascot."""
    duck = """[yellow]       __
     >(o )___
      ( .__> /
       `---'[/yellow]
      [cyan]~~[/cyan][yellow]**[/yellow][cyan]~~[/cyan]"""

    console.print()
    console.print(Panel(
        f"{duck}\n\n"
        "[bold cyan]Canvas Completer[/bold cyan]\n"
        "[dim]Your rubber duck for homework[/dim]",
        subtitle=f"[dim]v{VERSION} • by kn0ck0ut[/dim]",
        border_style="cyan",
        padding=(1, 4),
        width=50,
    ))
    console.print()


def get_course_assignments(course_path, days=30):
    """Get assignments for a specific course."""
    assignments = []
    assignments_dir = course_path / "assignments"

    if not assignments_dir.exists():
        return assignments

    now = datetime.now().astimezone()
    cutoff = now + timedelta(days=days)

    course_info_file = course_path / "course_info.json"
    if course_info_file.exists():
        with open(course_info_file) as f:
            course_info = json.load(f)
        course_name = course_info.get("name", course_path.name)
    else:
        course_name = course_path.name

    for a_dir in assignments_dir.iterdir():
        if not a_dir.is_dir():
            continue

        a_file = a_dir / "assignment.json"
        if not a_file.exists():
            continue

        with open(a_file) as f:
            a_info = json.load(f)

        due_at = a_info.get("due_at")
        due_date = None
        is_upcoming = False

        if due_at:
            try:
                due_date = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                if now <= due_date <= cutoff:
                    is_upcoming = True
            except:
                pass

        assignments.append({
            "name": a_info.get("name"),
            "course": course_name,
            "due_at": due_date,
            "points": a_info.get("points_possible"),
            "path": a_dir,
            "submitted": a_info.get("has_submitted", False),
            "is_graded": a_info.get("is_graded", False),
            "score": a_info.get("score"),
            "grade": a_info.get("grade"),
            "workflow_state": a_info.get("workflow_state", "unsubmitted"),
            "is_upcoming": is_upcoming,
        })

    # Sort by due date (None dates at end)
    assignments.sort(key=lambda x: (x["due_at"] is None, x["due_at"] or datetime.max.replace(tzinfo=now.tzinfo)))
    return assignments


def parse_course_display_name(name):
    """Extract human-readable course name from Canvas course name."""
    # Pattern: "2026WI_MSDS_462-DL_SEC55 Computer Vision" -> "Computer Vision"
    match = re.match(r'^\d{4}[A-Z]{2}_[A-Z]+_\d+-[A-Z]+_SEC\d+\s+(.+)$', name)
    if match:
        return match.group(1)
    return name


def is_current_course(term):
    """Check if a course is from the current academic year."""
    if not term:
        return False
    term_lower = term.lower()
    if 'program term' in term_lower:
        return True  # Always show program term courses

    # Parse year from term like "2026 Winter", "2025 Fall"
    match = re.match(r'^(\d{4})', term)
    if match:
        year = int(match.group(1))
        current_year = datetime.now().year
        # Current academic year: show current year and previous year (for fall terms)
        return year >= current_year - 1
    return False


def show_course_selection(show_archived=False):
    """Show course selection screen."""
    courses = get_sync_status()

    if not courses:
        return None

    # Separate current and archived courses
    current_courses = [c for c in courses if is_current_course(c.get('term'))]
    archived_courses = [c for c in courses if not is_current_course(c.get('term'))]

    # Sort courses: most upcoming assignments first, "program term" courses at the bottom
    def course_sort_key(c):
        term = (c.get('term') or '').lower()
        is_program_term = 'program term' in term
        return (1 if is_program_term else 0, -c['upcoming_count'], c['name'].lower())

    current_courses.sort(key=course_sort_key)
    archived_courses.sort(key=course_sort_key)

    # Determine which courses to display
    if show_archived:
        display_courses = current_courses + archived_courses
    else:
        display_courses = current_courses

    console.print("[bold]Select a Course:[/bold]")
    console.print()

    # Create table
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
    table.add_column("#", style="cyan", justify="right", width=3)
    table.add_column("Course")
    table.add_column("Due", justify="center")
    table.add_column("Synced", justify="right", style="dim")

    for i, c in enumerate(display_courses, 1):
        # Format upcoming count
        if c['upcoming_count'] > 0:
            upcoming_str = f"[yellow]{c['upcoming_count']}[/yellow]"
        else:
            upcoming_str = "[dim]—[/dim]"

        display_name = parse_course_display_name(c['name'])

        course_display = f"[bold]{display_name[:50]}[/bold]"
        if c.get('term'):
            course_display += f"\n[dim]{c['term']}[/dim]"

        table.add_row(
            str(i),
            course_display,
            upcoming_str,
            c["last_sync"],
        )

    console.print(table)
    console.print()

    # Show archived courses option
    if archived_courses and not show_archived:
        console.print(f"  [cyan]a[/cyan]) Show {len(archived_courses)} archived courses")
    elif show_archived and archived_courses:
        console.print(f"  [cyan]a[/cyan]) Hide archived courses")

    console.print(f"  [cyan]s[/cyan]) Sync courses")
    console.print(f"  [cyan]q[/cyan]) Quit")
    console.print()

    valid = [str(i) for i in range(1, len(display_courses) + 1)] + ["s", "q"]
    if archived_courses:
        valid.append("a")

    choice = Prompt.ask("Select", choices=valid, default="1" if display_courses else "s")

    if choice == "s":
        return "sync"
    elif choice == "q":
        return "quit"
    elif choice == "a":
        return ("toggle_archived", not show_archived)
    else:
        idx = int(choice) - 1
        return display_courses[idx]


def show_course_view(course):
    """Show the view for a specific course."""
    while True:
        console.clear()
        show_welcome()

        # Course header
        console.print(Panel(
            f"[bold]{course['name']}[/bold]\n"
            f"[dim]{course['term'] or 'Current Term'}[/dim]\n\n"
            f"Assignments: {course['assignment_count']} total, [yellow]{course['upcoming_count']} upcoming[/yellow]\n"
            f"Last synced: [dim]{course['last_sync']}[/dim]",
            title="Course",
            border_style="cyan",
            expand=True,
        ))
        console.print()

        # Get assignments for this course
        assignments = get_course_assignments(course['path'])
        upcoming = [a for a in assignments if a['is_upcoming']]

        # Show upcoming assignments
        if upcoming:
            submitted_count = sum(1 for a in upcoming if a["submitted"])
            status_note = ""
            if submitted_count == len(upcoming):
                status_note = " [green](all submitted!)[/green]"
            elif submitted_count > 0:
                status_note = f" [dim]({submitted_count}/{len(upcoming)} submitted)[/dim]"

            console.print(f"[bold]Upcoming Assignments:{status_note}[/bold]")
            console.print()

            for a in upcoming[:5]:
                due_str = a["due_at"].strftime("%a %b %d, %I:%M %p") if a["due_at"] else "No due date"
                points = f"({a['points']} pts)" if a['points'] else ""

                if a["is_graded"] and a["score"] is not None:
                    status = f"[green]★ {a['score']}/{a['points']}[/green] "
                elif a["submitted"]:
                    status = "[green]✓[/green] "
                else:
                    status = "[yellow]○[/yellow] "

                console.print(f"  {status}[bold]{a['name']}[/bold] {points}")
                console.print(f"    [dim]Due: {due_str}[/dim]")
                console.print()

            if len(upcoming) > 5:
                console.print(f"  [dim]... and {len(upcoming) - 5} more[/dim]")
                console.print()
        else:
            console.print("[green]No upcoming assignments![/green]")
            console.print()

        # Menu
        console.print("[bold]What would you like to do?[/bold]")
        console.print()
        console.print("  [cyan]1[/cyan]) Work on an assignment")
        console.print("  [cyan]2[/cyan]) View syllabus")
        console.print("  [cyan]3[/cyan]) View course materials")
        console.print("  [cyan]4[/cyan]) View all assignments")
        console.print("  [cyan]0[/cyan]) Back to course list")
        console.print()

        choice = Prompt.ask("Select", choices=["0", "1", "2", "3", "4"], default="1")

        if choice == "0":
            return
        elif choice == "1":
            # Work on assignment
            assignment = select_assignment_from_course(course, assignments)
            if assignment:
                show_work_menu(assignment)
        elif choice == "2":
            # View syllabus
            syllabus_file = course['path'] / "syllabus.md"
            if syllabus_file.exists():
                with open(syllabus_file) as f:
                    content = f.read()
                console.print()
                console.print(Panel(Markdown(content), title="Syllabus", border_style="cyan"))
            else:
                console.print("[yellow]No syllabus found for this course.[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "3":
            # View course materials
            modules_dir = course['path'] / "modules"
            if modules_dir.exists():
                modules = [d for d in modules_dir.iterdir() if d.is_dir()]
                # Sort by module number (extract number from "Module_1_..." or "Module 1...")
                def module_sort_key(m):
                    match = re.search(r'Module[_\s]*(\d+)', m.name, re.IGNORECASE)
                    if match:
                        return (0, int(match.group(1)))  # Numbered modules first, by number
                    return (1, m.name.lower())  # Non-numbered modules after, alphabetically
                modules.sort(key=module_sort_key)
                if modules:
                    console.print()
                    console.print("[bold]Course Materials:[/bold]")
                    console.print()
                    for i, m in enumerate(modules, 1):
                        console.print(f"  [cyan]{i}[/cyan]) {m.name.replace('_', ' ')}")
                    console.print(f"  [cyan]0[/cyan]) Back")
                    console.print()

                    mod_choice = Prompt.ask("Select", default="0")
                    try:
                        idx = int(mod_choice)
                        if 1 <= idx <= len(modules):
                            content_file = modules[idx-1] / "content.md"
                            if content_file.exists():
                                with open(content_file) as f:
                                    content = f.read()
                                console.print()
                                console.print(Panel(Markdown(content), title=modules[idx-1].name.replace('_', ' '), border_style="magenta"))
                    except:
                        pass
                else:
                    console.print("[yellow]No course materials found.[/yellow]")
            else:
                console.print("[yellow]No course materials found. Run sync to fetch them.[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "4":
            # View all assignments
            console.print()
            console.print("[bold]All Assignments:[/bold]")
            console.print()
            for a in assignments:
                due_str = a["due_at"].strftime("%b %d") if a["due_at"] else "No date"
                if a["is_graded"] and a["score"] is not None:
                    status = f"[green]★ {a['score']}/{a['points']}[/green]"
                elif a["submitted"]:
                    status = "[green]✓[/green]"
                else:
                    status = "[dim]○[/dim]"
                console.print(f"  {status} {a['name'][:50]} [dim]({due_str})[/dim]")
            input("\nPress Enter to continue...")


def select_assignment_from_course(course, assignments):
    """Select an assignment from the course."""
    if not assignments:
        console.print("[yellow]No assignments found.[/yellow]")
        input("\nPress Enter to continue...")
        return None

    # Show upcoming first, then others
    upcoming = [a for a in assignments if a['is_upcoming']]
    past = [a for a in assignments if not a['is_upcoming']]

    console.print()
    console.print("[bold]Select an assignment:[/bold]")
    console.print()

    all_assignments = upcoming + past[:5]  # Show upcoming + some past

    for i, a in enumerate(all_assignments, 1):
        due_str = a["due_at"].strftime("%a %b %d") if a["due_at"] else "No date"
        points = f"({a['points']} pts)" if a['points'] else ""

        if a["is_graded"] and a["score"] is not None:
            status = f"[green]★[/green] "
        elif a["submitted"]:
            status = "[green]✓[/green] "
        elif a['is_upcoming']:
            status = "[yellow]○[/yellow] "
        else:
            status = "[dim]○[/dim] "

        label = "[dim](past)[/dim]" if not a['is_upcoming'] else ""
        console.print(f"  [cyan]{i}[/cyan]) {status}{a['name'][:45]} {points} {label}")
        console.print(f"      [dim]Due: {due_str}[/dim]")

    console.print()
    console.print(f"  [cyan]0[/cyan]) Back")
    console.print()

    valid = [str(i) for i in range(len(all_assignments) + 1)]
    choice = Prompt.ask("Select", choices=valid, default="1" if all_assignments else "0")

    if choice == "0":
        return None

    idx = int(choice) - 1
    return all_assignments[idx]


def show_status_dashboard():
    """Show current status of all courses and upcoming work."""
    courses = get_sync_status()
    upcoming = get_upcoming_assignments(days=7)

    # Authentication status
    if is_authenticated():
        console.print("[green]●[/green] Authenticated with Canvas")
    else:
        console.print("[red]●[/red] Not authenticated - run [bold]sync[/bold] to log in")
        return False

    console.print()

    # Course status table
    if courses:
        table = Table(title="Your Courses", box=box.ROUNDED)
        table.add_column("Course", style="cyan")
        table.add_column("Term", style="dim")
        table.add_column("Assignments", justify="center")
        table.add_column("Upcoming", justify="center")
        table.add_column("Syllabus", justify="center")
        table.add_column("Last Sync", justify="right", style="dim")

        for c in courses:
            syllabus_status = "[green]✓[/green]" if c["has_syllabus"] else "[dim]—[/dim]"
            upcoming_style = "[yellow]" if c["upcoming_count"] > 0 else "[dim]"
            table.add_row(
                c["name"][:40] + ("..." if len(c["name"]) > 40 else ""),
                c["term"] or "—",
                str(c["assignment_count"]),
                f"{upcoming_style}{c['upcoming_count']}[/]",
                syllabus_status,
                c["last_sync"],
            )

        console.print(table)
        console.print()
    else:
        console.print("[yellow]No courses synced yet.[/yellow]")
        console.print("Run [bold cyan]sync[/bold cyan] to fetch your courses and assignments.")
        console.print()
        return True

    # Upcoming assignments
    if upcoming:
        # Count submitted vs total
        submitted_count = sum(1 for a in upcoming if a["submitted"])
        total_count = len(upcoming)

        status_summary = ""
        if submitted_count == total_count:
            status_summary = " [green](all submitted!)[/green]"
        elif submitted_count > 0:
            status_summary = f" [dim]({submitted_count}/{total_count} submitted)[/dim]"

        console.print(f"[bold]Upcoming Assignments (next 7 days):{status_summary}[/bold]")
        console.print()

        for a in upcoming[:6]:
            due_str = a["due_at"].strftime("%a %b %d, %I:%M %p")
            points = f"({a['points']} pts)" if a['points'] else ""

            # Status indicator
            if a["is_graded"] and a["score"] is not None:
                status = f"[green]★ {a['score']}/{a['points']}[/green] "
            elif a["submitted"]:
                status = "[green]✓[/green] "
            else:
                status = "[yellow]○[/yellow] "

            console.print(f"  {status}[bold]{a['name']}[/bold] {points}")
            console.print(f"    [dim]{a['course']}[/dim]")
            console.print(f"    [yellow]Due: {due_str}[/yellow]")
            console.print()

        if len(upcoming) > 6:
            console.print(f"  [dim]... and {len(upcoming) - 6} more[/dim]")
            console.print()
    else:
        console.print("[green]No assignments due in the next 7 days![/green]")
        console.print()

    return True


def show_main_menu():
    """Show main menu and handle selection."""
    courses = get_sync_status()
    has_data = len(courses) > 0

    console.print("[bold]What would you like to do?[/bold]")
    console.print()

    options = []

    if has_data:
        options.append(("1", "View assignment details", "view"))
        options.append(("2", "Sync courses (refresh data)", "sync"))
        options.append(("3", "Work on an assignment", "work"))
    else:
        options.append(("1", "Sync courses [recommended]", "sync"))

    options.append(("s", "Settings", "settings"))
    options.append(("q", "Quit", "quit"))

    for key, label, _ in options:
        if "recommended" in label.lower():
            console.print(f"  [bold cyan]{key}[/bold cyan]) {label}")
        else:
            console.print(f"  [cyan]{key}[/cyan]) {label}")

    console.print()

    valid_keys = [o[0] for o in options]
    choice = Prompt.ask("Select option", choices=valid_keys, default=valid_keys[0])

    for key, _, action in options:
        if choice == key:
            return action

    return "quit"


def run_sync(force_browser=False):
    """Run the sync process. Tries headless first, falls back to browser if needed."""
    console.print()
    console.print("[bold]Starting Canvas sync...[/bold]")

    # Try headless sync first (no browser needed)
    if not force_browser:
        console.print("[dim]Trying headless sync with saved session...[/dim]")
        result = canvas.try_headless_sync(days_ahead=14)
        if result is not None:
            return True
        console.print("[yellow]Session expired or invalid. Opening browser to login...[/yellow]")

    # Fall back to browser-based sync
    console.print("[dim]A browser window will open for authentication.[/dim]")
    console.print()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        session_path = canvas.load_session()
        browser = p.chromium.launch(headless=False)

        if session_path:
            console.print("[dim]Loading saved session...[/dim]")
            try:
                context = browser.new_context(storage_state=session_path)
            except:
                context = browser.new_context()
        else:
            context = browser.new_context()

        page = context.new_page()
        logged_in = canvas.check_if_logged_in(page)

        if not logged_in:
            page.goto(canvas.CANVAS_BASE_URL)
            if not canvas.wait_for_canvas_login(page):
                browser.close()
                return False
            canvas.save_session(context)
        else:
            console.print("[green]Already logged in![/green]")

        canvas.sync_all_data(page, days_ahead=14)
        browser.close()

    return True


def view_assignments():
    """View and select assignments."""
    upcoming = get_upcoming_assignments(days=30)

    if not upcoming:
        console.print("[yellow]No upcoming assignments found.[/yellow]")
        return None

    console.print()
    console.print("[bold]Select an assignment to view details:[/bold]")
    console.print()

    for i, a in enumerate(upcoming, 1):
        due_str = a["due_at"].strftime("%a %b %d, %I:%M %p")
        points = f"({a['points']} pts)" if a['points'] else ""

        # Show submission status
        if a.get("is_graded") and a.get("score") is not None:
            status = f"[green]★ {a['score']}/{a['points']}[/green] "
        elif a.get("submitted"):
            status = "[green]✓[/green] "
        else:
            status = ""

        console.print(f"  [cyan]{i}[/cyan]) {status}[bold]{a['name']}[/bold] {points}")
        console.print(f"      [dim]{a['course']} — Due: {due_str}[/dim]")

    console.print()
    console.print(f"  [cyan]0[/cyan]) Back to main menu")
    console.print()

    choice = Prompt.ask("Select", default="0")

    try:
        idx = int(choice)
        if idx == 0:
            return None
        if 1 <= idx <= len(upcoming):
            return upcoming[idx - 1]
    except:
        pass

    return None


def show_assignment_details(assignment):
    """Show full details of an assignment."""
    console.print()

    # Read requirements
    req_file = assignment["path"] / "requirements.md"
    if req_file.exists():
        with open(req_file) as f:
            content = f.read()
        console.print(Panel(Markdown(content), title="Assignment Details", border_style="cyan"))
    else:
        console.print("[yellow]No requirements file found.[/yellow]")

    # Read rubric if available
    rubric_file = assignment["path"] / "rubric.md"
    if rubric_file.exists():
        with open(rubric_file) as f:
            content = f.read()
        console.print()
        console.print(Panel(Markdown(content), title="Grading Rubric", border_style="green"))

    console.print()
    console.print(f"[dim]Local path: {assignment['path']}[/dim]")
    console.print()

    input("Press Enter to continue...")


def check_tool(command):
    """Check if a CLI tool is available."""
    import subprocess
    try:
        result = subprocess.run(
            ["which", command],
            capture_output=True,
            check=True
        )
        return result.stdout.decode().strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def has_tmux():
    """Check if tmux is available."""
    return check_tool("tmux") is not None


def has_claude():
    """Check if Claude Code CLI is available."""
    return check_tool("claude") is not None


def has_cursor_agent():
    """Check if Cursor Agent CLI is available."""
    return check_tool("agent") is not None


def in_tmux():
    """Check if we're already running inside tmux."""
    import os
    return os.environ.get("TMUX") is not None


def get_tool_status():
    """Get status of all required/optional tools."""
    return {
        "claude": has_claude(),
        "cursor": has_cursor_agent(),
        "tmux": has_tmux(),
    }


def show_tool_status():
    """Display tool installation status."""
    tools = get_tool_status()

    console.print()
    console.print("[bold]Tool Status:[/bold]")
    console.print()

    # Claude Code
    if tools["claude"]:
        console.print("  [green]✓[/green] Claude Code [dim](claude)[/dim]")
    else:
        console.print("  [red]✗[/red] Claude Code [dim]- not installed[/dim]")

    # Cursor Agent
    if tools["cursor"]:
        console.print("  [green]✓[/green] Cursor Agent [dim](agent)[/dim]")
    else:
        console.print("  [red]✗[/red] Cursor Agent [dim]- not installed[/dim]")

    # tmux
    if tools["tmux"]:
        console.print("  [green]✓[/green] tmux [dim](split panes)[/dim]")
    else:
        console.print("  [dim]○[/dim] tmux [dim]- optional, for split panes[/dim]")

    console.print()
    return tools


def show_tool_setup_guide():
    """Show guide for installing missing tools."""
    tools = get_tool_status()

    if tools["claude"] and tools["cursor"]:
        return  # All good!

    console.print()
    console.print(Panel(
        "[bold]Setup Required Tools[/bold]\n\n"
        + (
            "[bold]Claude Code[/bold] [dim](recommended)[/dim]\n"
            "  [cyan]npm install -g @anthropic-ai/claude-code[/cyan]\n\n"
            if not tools["claude"] else ""
        )
        + (
            "[bold]Cursor Agent[/bold]\n"
            "  Install Cursor from [cyan]https://cursor.com[/cyan]\n"
            "  Then enable CLI: Cursor → Settings → Enable 'agent' command\n\n"
            if not tools["cursor"] else ""
        )
        + (
            "[bold]tmux[/bold] [dim](optional - enables split panes)[/dim]\n"
            "  [cyan]brew install tmux[/cyan]\n"
            if not tools["tmux"] else ""
        ),
        title="Installation Guide",
        border_style="yellow",
    ))
    console.print()


def find_relevant_modules(assignment):
    """Find module content that might be relevant to an assignment."""
    course_path = assignment["path"].parent.parent  # Go up from assignments/{name} to course
    modules_dir = course_path / "modules"

    if not modules_dir.exists():
        return []

    relevant = []
    for module_dir in modules_dir.iterdir():
        if module_dir.is_dir():
            content_file = module_dir / "content.md"
            if content_file.exists():
                relevant.append({
                    "name": module_dir.name.replace("_", " "),
                    "path": content_file,
                })

    return relevant


def build_claude_prompt(assignment):
    """Build the prompt for Claude Code."""
    req_file = assignment["path"] / "requirements.md"
    rubric_file = assignment["path"] / "rubric.md"
    submission_dir = assignment["path"] / "submission"

    # Create submission directory if it doesn't exist
    submission_dir.mkdir(parents=True, exist_ok=True)

    prompt_parts = [
        f"I need help completing this assignment: {assignment['name']}",
        f"Course: {assignment['course']}",
        f"Due: {assignment['due_at'].strftime('%a %b %d, %I:%M %p')}",
        "",
        f"Please read the assignment requirements at: {req_file}",
    ]

    if rubric_file.exists():
        prompt_parts.append(f"And the grading rubric at: {rubric_file}")

    # Include module content if available
    modules = find_relevant_modules(assignment)
    if modules:
        prompt_parts.append("")
        prompt_parts.append("Relevant course materials are available at:")
        for mod in modules[:5]:  # Limit to 5 most recent
            prompt_parts.append(f"  - {mod['name']}: {mod['path']}")

    prompt_parts.append("")
    prompt_parts.append("Help me understand what I need to do and guide me through completing it.")
    prompt_parts.append("Reference the course materials when relevant to ensure accuracy.")

    # Writing style instructions for authentic student voice
    prompt_parts.append("")
    prompt_parts.append("=" * 50)
    prompt_parts.append("WRITING STYLE GUIDELINES")
    prompt_parts.append("=" * 50)
    prompt_parts.append("")
    prompt_parts.append("You're helping a graduate student with their assignment.")
    prompt_parts.append("")
    prompt_parts.append("WRITING STYLE:")
    prompt_parts.append("- Write as a B+/A- student who cares but isn't perfect")
    prompt_parts.append("- Write clearly but occasionally:")
    prompt_parts.append("  - Start sentences with conjunctions when it flows naturally")
    prompt_parts.append("  - Use contractions in less formal sections")
    prompt_parts.append("  - Have minor inconsistencies (switching between 'the author argues' and 'the author states')")
    prompt_parts.append("  - Include 1-2 awkward phrasings per page that a human would write but not catch")
    prompt_parts.append("- Understand the material well but explain it like a student, not a textbook")
    prompt_parts.append("")
    prompt_parts.append("CONSTRAINTS:")
    prompt_parts.append("- Match the length requirement but don't be suspiciously verbose")
    prompt_parts.append("- If the rubric asks for 3 examples, give exactly 3 (not an overachieving 4)")
    prompt_parts.append("- Don't use uncommon SAT vocabulary words unless they genuinely fit")
    prompt_parts.append("- Avoid the phrases: 'delve into', 'tapestry', 'multifaceted', 'in today's society'")
    prompt_parts.append("- Reference specific page numbers from readings when relevant")
    prompt_parts.append("- Show your work on calculations; include minor arithmetic notation")
    prompt_parts.append("")
    prompt_parts.append("CRITICAL:")
    prompt_parts.append("- Make the introduction adequate, not brilliant")
    prompt_parts.append("- Include actual opinions/interpretations, not just summary")
    prompt_parts.append("- If citing sources, use the citation format slightly imperfectly (students mess up APA/MLA)")
    prompt_parts.append("")
    prompt_parts.append("=" * 50)
    prompt_parts.append("")
    prompt_parts.append(f"IMPORTANT: Save all work to the submission folder: {submission_dir}")
    prompt_parts.append("  - Save your working draft to: draft.md")
    prompt_parts.append("  - Save the final completed submission to: final.md")
    prompt_parts.append("  - Save any code files with appropriate extensions (.py, .ipynb, etc.)")
    prompt_parts.append("  - Update the files as we work through the assignment together.")

    return "\n".join(prompt_parts)


def launch_claude_code(assignment):
    """Launch Claude Code with assignment context."""
    import subprocess
    import os

    prompt = build_claude_prompt(assignment)

    # Check if tmux is available and we're in tmux
    if has_tmux() and in_tmux():
        console.print()
        console.print("[bold]Launching Claude Code in split pane...[/bold]")
        console.print()
        input("Press Enter to open Claude Code →")

        # Create a split pane and run claude in it
        escaped_prompt = prompt.replace('"', '\\"').replace("'", "'\\''")
        tmux_cmd = f"tmux split-window -h 'claude \"{escaped_prompt}\"'"
        os.system(tmux_cmd)

        # Show waiting screen
        show_wait_screen(assignment['name'], "Claude Code")
        return True

    elif has_tmux() and not in_tmux():
        # Tmux available but not in a session - offer to create one
        console.print()
        console.print("[bold]tmux detected![/bold]")
        console.print()
        console.print("Would you like to open in a new tmux session with split panes?")
        console.print("[dim]This will let you see instructions alongside Claude Code.[/dim]")
        console.print()

        if Confirm.ask("Use tmux split pane?", default=True):
            escaped_prompt = prompt.replace('"', '\\"').replace("'", "'\\''")
            assignment_name = assignment['name'].replace('"', '\\"')
            script_path = Path(__file__).resolve()

            # Create new tmux session with wait screen on left, Claude on right
            os.system(f'tmux new-session -d -s canvas-completer \'python3 "{script_path}" --wait "{assignment_name}" "Claude Code"\'')
            os.system(f'tmux split-window -h -t canvas-completer \'claude "{escaped_prompt}"\'')
            os.system('tmux attach -t canvas-completer')
            return True

    # No tmux or user declined - show instructions and launch directly
    console.print()
    console.print(Panel(
        "[bold]Launching Claude Code[/bold]\n\n"
        "Claude Code will open in this terminal.\n\n"
        "[bold]To exit Claude Code and return here:[/bold]\n"
        "  • Type [cyan]/exit[/cyan] or [cyan]exit[/cyan]\n"
        "  • Or press [cyan]Ctrl+C[/cyan] twice\n\n"
        "[dim]Canvas Completer will resume when you're done.[/dim]",
        border_style="yellow",
        width=55,
    ))
    console.print()
    input("Press Enter to launch Claude Code...")

    # Launch claude
    try:
        os.system(f'claude "{prompt}"')
        console.print()
        console.print("[green]Welcome back![/green] Returning to Canvas Completer...")
        console.print()
        input("Press Enter to continue...")
        return True
    except Exception as e:
        console.print(f"[red]Error launching Claude Code: {e}[/red]")
        console.print("[dim]Make sure Claude Code is installed: npm install -g @anthropic-ai/claude-code[/dim]")
        return False


def launch_cursor(assignment):
    """Launch Cursor Agent with assignment directory."""
    import subprocess
    import os

    path = assignment["path"]

    # Check if tmux is available and we're in tmux
    if has_tmux() and in_tmux():
        console.print()
        console.print("[bold]Launching Cursor Agent in split pane...[/bold]")
        console.print()
        input("Press Enter to open Cursor Agent →")

        # Create a split pane and run cursor agent in it
        tmux_cmd = f"tmux split-window -h 'cd \"{path}\" && agent'"
        os.system(tmux_cmd)

        # Show waiting screen
        show_wait_screen(assignment['name'], "Cursor Agent")
        return True

    elif has_tmux() and not in_tmux():
        # Tmux available but not in a session - offer to create one
        console.print()
        console.print("[bold]tmux detected![/bold]")
        console.print()
        console.print("Would you like to open in a new tmux session with split panes?")
        console.print("[dim]This will let you see instructions alongside Cursor Agent.[/dim]")
        console.print()

        if Confirm.ask("Use tmux split pane?", default=True):
            assignment_name = assignment['name'].replace('"', '\\"')
            script_path = Path(__file__).resolve()

            # Create new tmux session with wait screen on left, Cursor on right
            os.system(f'tmux new-session -d -s canvas-completer \'python3 "{script_path}" --wait "{assignment_name}" "Cursor Agent"\'')
            os.system(f'tmux split-window -h -t canvas-completer \'cd "{path}" && agent\'')
            os.system('tmux attach -t canvas-completer')
            return True

    # No tmux or user declined - show instructions and launch directly
    console.print()
    console.print(Panel(
        "[bold]Launching Cursor Agent[/bold]\n\n"
        "Cursor Agent will open in this terminal.\n\n"
        "[bold]To exit and return here:[/bold]\n"
        "  • Type [cyan]exit[/cyan] or press [cyan]Ctrl+C[/cyan]\n\n"
        "[dim]Canvas Completer will resume when you're done.[/dim]",
        border_style="yellow",
        width=55,
    ))
    console.print()
    input("Press Enter to launch Cursor Agent...")

    try:
        os.system(f'cd "{assignment["path"]}" && agent')
        console.print()
        console.print("[green]Welcome back![/green] Returning to Canvas Completer...")
        console.print()
        input("Press Enter to continue...")
        return True
    except FileNotFoundError:
        console.print("[red]Cursor Agent CLI not found.[/red]")
        console.print("[dim]Make sure Cursor is installed and 'agent' is in your PATH.[/dim]")
        return False
    except Exception as e:
        console.print(f"[red]Error launching Cursor Agent: {e}[/red]")
        return False


def get_submission_status(assignment):
    """Check submission folder and return detailed status.

    Status flow:
    1. not_started - No work yet
    2. draft_in_progress - Working on draft.md
    3. final_ready - final.md exists, needs AI check
    4. ai_checking - AI check in progress (not used currently)
    5. ai_high - AI score >= 30%, humanization recommended
    6. ai_passed - AI score < 30%, good to go
    7. humanized - Humanized version created and passed
    8. ready_to_submit - Final is ready for submission
    """
    submission_dir = assignment["path"] / "submission"

    if not submission_dir.exists():
        return "not_started", None, None

    files = list(submission_dir.iterdir()) if submission_dir.exists() else []
    file_names = [f.name for f in files]

    if "final.md" not in file_names:
        if "draft.md" in file_names:
            return "draft_in_progress", files, None
        elif files:
            return "work_started", files, None
        else:
            return "not_started", None, None

    # We have a final.md - check AI detection status
    ai_cache_file = submission_dir / "ai_check.json"
    ai_score = None
    humanized_score = None

    # Check main AI score
    if ai_cache_file.exists():
        try:
            import json
            with open(ai_cache_file) as f:
                cached = json.load(f)
            for service, data in cached.get("services", {}).items():
                if data.get("score") is not None:
                    ai_score = data.get("score")
                    break
        except:
            pass

    # Check humanized score
    for humanized_name in ["final_humanized.md", "draft_humanized.md"]:
        if humanized_name in file_names:
            humanized_cache = submission_dir / f"ai_check_{humanized_name.replace('.md', '')}.json"
            if humanized_cache.exists():
                try:
                    with open(humanized_cache) as f:
                        h_cached = json.load(f)
                    for service, data in h_cached.get("services", {}).items():
                        if data.get("score") is not None:
                            humanized_score = data.get("score")
                            break
                except:
                    pass
            break

    scores = {"ai_score": ai_score, "humanized_score": humanized_score}

    # Determine status based on scores
    if ai_score is None:
        return "final_ready", files, scores  # Has final but no AI check yet

    if humanized_score is not None:
        if humanized_score < 30:
            return "ready_to_submit", files, scores
        else:
            return "ai_high", files, scores  # Humanized but still high

    if ai_score < 30:
        return "ready_to_submit", files, scores
    else:
        return "ai_high", files, scores  # High AI, needs humanization


def get_ai_detection_display(assignment):
    """Get AI detection status for display in header."""
    submission_dir = assignment["path"] / "submission"
    if not submission_dir.exists():
        return None, None, True

    try:
        from ai_detector import load_cached_results, format_detection_results, needs_recheck, check_zerogpt_api, get_text_hash

        cached = load_cached_results(submission_dir)

        # Check if we have a humanized version with a cached score
        humanized_score = None
        for humanized_name in ["final_humanized.md", "draft_humanized.md"]:
            humanized_path = submission_dir / humanized_name
            if humanized_path.exists():
                # Check if we have a cached score for the humanized version
                humanized_cache_file = submission_dir / f"ai_check_{humanized_name.replace('.md', '')}.json"
                if humanized_cache_file.exists():
                    import json
                    with open(humanized_cache_file) as f:
                        humanized_cached = json.load(f)
                    for service, data in humanized_cached.get("services", {}).items():
                        if data.get("score") is not None:
                            humanized_score = data.get("score")
                            break
                break

        if cached:
            status_line, time_ago = format_detection_results(cached)
            needs_update = needs_recheck(submission_dir)

            # Add humanized score if available
            if humanized_score is not None:
                if humanized_score < 20:
                    status_line += f" | [green]humanized: {humanized_score:.0f}%[/green]"
                elif humanized_score < 50:
                    status_line += f" | [yellow]humanized: {humanized_score:.0f}%[/yellow]"
                else:
                    status_line += f" | [red]humanized: {humanized_score:.0f}%[/red]"

            return status_line, time_ago, needs_update
        return None, None, True
    except Exception:
        return None, None, True


def run_ai_check_background(assignment):
    """Run AI detection in background and return results."""
    submission_dir = assignment["path"] / "submission"
    if not submission_dir.exists():
        return None

    try:
        from ai_detector import run_detection_for_submission
        console.print("[dim]Running AI detection in background...[/dim]")
        results = run_detection_for_submission(submission_dir, force=True)
        return results
    except Exception as e:
        console.print(f"[red]AI detection error: {e}[/red]")
        return None


def get_workflow_display(sub_status, scores, submitted_to_canvas=False):
    """Generate workflow progress display."""
    # Define the stages
    stages = [
        ("not_started", "Start", "○"),
        ("draft", "Draft", "○"),
        ("final", "Final", "○"),
        ("ai_check", "AI Check", "○"),
        ("submit", "Submit", "○"),
    ]

    # Determine which stage we're at and what's complete
    if submitted_to_canvas:
        completed = ["not_started", "draft", "final", "ai_check", "submit"]
        current = None
        next_action = None
    elif sub_status == "not_started":
        completed = []
        current = "not_started"
        next_action = "Open in Claude Code to start writing"
    elif sub_status in ["work_started", "draft_in_progress"]:
        completed = ["not_started"]
        current = "draft"
        next_action = "Continue writing and save as final.md when done"
    elif sub_status == "final_ready":
        completed = ["not_started", "draft", "final"]
        current = "ai_check"
        next_action = "Run AI detection to check your writing"
    elif sub_status == "ai_high":
        completed = ["not_started", "draft", "final"]
        current = "ai_check"
        ai_score = scores.get("ai_score", 0) if scores else 0
        next_action = f"AI score is {ai_score:.0f}% - consider humanizing"
    elif sub_status == "ready_to_submit":
        completed = ["not_started", "draft", "final", "ai_check"]
        current = "submit"
        next_action = "Ready! Submit to Canvas"
    else:
        completed = []
        current = "not_started"
        next_action = "Open in Claude Code to start writing"

    # Build the progress bar
    progress_parts = []
    for stage_id, stage_name, symbol in stages:
        if stage_id in completed:
            progress_parts.append(f"[green]✓ {stage_name}[/green]")
        elif stage_id == current:
            progress_parts.append(f"[yellow]● {stage_name}[/yellow]")
        else:
            progress_parts.append(f"[dim]○ {stage_name}[/dim]")

    progress_line = " → ".join(progress_parts)

    return progress_line, next_action


def show_work_menu(assignment):
    """Show menu for working on a specific assignment."""
    while True:
        console.clear()
        console.print()

        # Check submission status (now returns 3 values)
        sub_status, sub_files, scores = get_submission_status(assignment)

        # Determine display status
        due_str = assignment["due_at"].strftime("%a %b %d, %I:%M %p")
        submitted_to_canvas = assignment.get("submitted", False)

        # Get workflow display
        progress_line, next_action = get_workflow_display(sub_status, scores, submitted_to_canvas)

        # Status text
        if submitted_to_canvas:
            status = "[green]✓ Submitted to Canvas[/green]"
        elif sub_status == "ready_to_submit":
            status = "[green]✓ Ready for submission[/green]"
        elif sub_status == "ai_high":
            status = "[yellow]⚠ AI detection high[/yellow]"
        elif sub_status == "final_ready":
            status = "[cyan]◐ Final ready - check AI[/cyan]"
        elif sub_status == "draft_in_progress":
            status = "[yellow]◐ Draft in progress[/yellow]"
        elif sub_status == "work_started":
            status = "[yellow]◐ Work started[/yellow]"
        else:
            status = "[dim]○ Not started[/dim]"

        # Get AI detection status for display
        ai_display = None
        ai_time = None
        ai_needs_update = False
        if sub_status != "not_started":
            result = get_ai_detection_display(assignment)
            if result[0]:
                ai_display, ai_time, ai_needs_update = result

        duck = """[yellow]       __
     >(o )___
      ( .__> /
       `---'[/yellow]  [italic]"Duck it! Let's do it live!"[/italic]
      [cyan]~~[/cyan][yellow]**[/yellow][cyan]~~[/cyan]"""

        # Build panel content
        panel_content = f"{duck}\n\n"
        panel_content += f"[bold]{assignment['name']}[/bold]\n"
        panel_content += f"[dim]{assignment['course']}[/dim]\n\n"
        panel_content += f"Due: [yellow]{due_str}[/yellow]\n"
        panel_content += f"Status: {status}\n"
        panel_content += f"Points: {assignment.get('points', 'N/A')}\n"

        # Add workflow progress
        panel_content += f"\n{progress_line}"

        # Add next action hint
        if next_action:
            panel_content += f"\n\n[bold cyan]Next:[/bold cyan] {next_action}"

        # Add AI detection line if available
        if ai_display:
            update_note = " [dim](files changed)[/dim]" if ai_needs_update else ""
            panel_content += f"\n\n[dim]AI Detection: {ai_display}{update_note}[/dim]"
            if ai_time:
                panel_content += f"\n[dim]Checked: {ai_time}[/dim]"

        console.print(Panel(
            panel_content,
            title="Active Assignment",
            border_style="cyan",
            expand=True,
        ))
        console.print()

        # Check available tools
        tools = get_tool_status()
        has_work = sub_status != "not_started"
        has_final = sub_status in ["final_ready", "ai_high", "ready_to_submit"]

        console.print("[bold]What would you like to do?[/bold]")
        console.print()

        # Build menu options based on available tools
        valid_choices = ["0", "3", "4", "5", "6", "7", "t"]

        # Show submission option first and highlighted if there's work
        if has_work:
            file_count = len(sub_files) if sub_files else 0
            console.print(f"  [bold green]v[/bold green]) [bold green]View my submission/work ({file_count} files)[/bold green]")
            valid_choices.append("v")

            # AI detection option - highlight if final is ready and not yet checked
            if sub_status == "final_ready":
                console.print(f"  [bold yellow]c[/bold yellow]) [bold yellow]Check AI detection[/bold yellow] [dim](recommended)[/dim]")
            elif sub_status == "ai_high":
                console.print(f"  [bold yellow]c[/bold yellow]) [bold yellow]Humanize text[/bold yellow] [dim](AI score high)[/dim]")
            elif ai_needs_update:
                console.print(f"  [bold yellow]c[/bold yellow]) [bold yellow]Check AI detection[/bold yellow] [dim](files changed)[/dim]")
            else:
                console.print(f"  [cyan]c[/cyan]) Check AI detection")
            valid_choices.append("c")
            console.print()

        if tools["claude"]:
            console.print("  [cyan]1[/cyan]) [bold]Open in Claude Code[/bold] [dim](recommended)[/dim]")
            valid_choices.append("1")
        else:
            console.print("  [dim]1) Open in Claude Code (not installed)[/dim]")

        if tools["cursor"]:
            console.print("  [cyan]2[/cyan]) Open in Cursor Agent")
            valid_choices.append("2")
        else:
            console.print("  [dim]2) Open in Cursor Agent (not installed)[/dim]")

        console.print("  [cyan]3[/cyan]) View full requirements")
        console.print("  [cyan]4[/cyan]) View grading rubric")
        console.print("  [cyan]5[/cyan]) View course materials")
        if not has_work:
            console.print("  [dim]6) View my submission/work (none yet)[/dim]")
        console.print("  [cyan]7[/cyan]) Open in browser")
        console.print("  [cyan]t[/cyan]) Tool setup guide")
        console.print("  [cyan]0[/cyan]) Back to main menu")
        console.print()

        # Set default choice based on workflow stage
        if sub_status == "final_ready":
            default_choice = "c"  # Prompt to check AI
        elif sub_status == "ai_high":
            default_choice = "c"  # Prompt to humanize
        elif sub_status == "ready_to_submit":
            default_choice = "v"  # View the ready submission
        elif has_work:
            default_choice = "1" if tools["claude"] else ("2" if tools["cursor"] else "v")  # Continue working
        elif tools["claude"]:
            default_choice = "1"
        elif tools["cursor"]:
            default_choice = "2"
        else:
            default_choice = "3"

        choice = Prompt.ask("Select", choices=valid_choices, default=default_choice)

        if choice == "0":
            return
        elif choice == "1":
            # Launch Claude Code
            launch_claude_code(assignment)
            # Don't return - stay in menu after Claude exits
        elif choice == "2":
            # Launch Cursor Agent
            launch_cursor(assignment)
            # Don't return - stay in menu after Cursor exits
        elif choice == "v" or choice == "6":
            # View submission/work
            submission_dir = assignment["path"] / "submission"
            if submission_dir.exists():
                files = list(submission_dir.iterdir())
                if files:
                    console.print()
                    console.print("[bold]Your Submission Files:[/bold]")
                    console.print(f"[dim]Location: {submission_dir}[/dim]")
                    console.print()

                    for i, f in enumerate(files, 1):
                        size = f.stat().st_size
                        size_str = f"{size} bytes" if size < 1024 else f"{size/1024:.1f} KB"
                        console.print(f"  [cyan]{i}[/cyan]) {f.name} [dim]({size_str})[/dim]")

                    console.print(f"  [cyan]0[/cyan]) Back")
                    console.print()

                    file_choice = Prompt.ask("Select file to view", default="0")
                    try:
                        idx = int(file_choice)
                        if 1 <= idx <= len(files):
                            selected_file = files[idx-1]
                            if selected_file.suffix in ['.md', '.txt', '.py', '.json']:
                                with open(selected_file) as sf:
                                    content = sf.read()
                                console.print()
                                console.print(Panel(content, title=selected_file.name, border_style="green"))
                            else:
                                console.print(f"[dim]File: {selected_file}[/dim]")
                    except:
                        pass
                else:
                    console.print("[yellow]Submission folder is empty. Work on the assignment to create files.[/yellow]")
            else:
                console.print("[yellow]No submission folder yet. Open in Claude Code to start working.[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "c":
            # Run AI detection
            console.print()
            console.print("[bold]AI Detection Check[/bold]")
            console.print()
            console.print("  [cyan]1[/cyan]) Quick check (ZeroGPT API)")
            console.print("  [cyan]2[/cyan]) Manual check (copy to clipboard & open site)")
            console.print("  [cyan]0[/cyan]) Cancel")
            console.print()

            check_choice = Prompt.ask("Select", choices=["0", "1", "2"], default="1")

            if check_choice == "0":
                continue

            console.print()

            # Run the appropriate check
            submission_dir = assignment["path"] / "submission"

            # Read submission text first - prefer final over draft
            text = ""
            source_file = None
            for filename in ["final.md", "draft.md"]:
                filepath = submission_dir / filename
                if filepath.exists():
                    with open(filepath) as f:
                        text = f.read()
                    source_file = filename
                    break

            if not text:
                console.print("[yellow]No submission files found (draft.md or final.md)[/yellow]")
                input("\nPress Enter to continue...")
                continue

            console.print(f"[dim]Checking: {source_file}[/dim]")

            if check_choice == "2":
                # Manual clipboard approach
                from ai_detector import open_detector_with_clipboard
                console.print("[dim]Copying text to clipboard and opening ZeroGPT...[/dim]")
                result = open_detector_with_clipboard(text, "zerogpt")
                console.print()
                console.print(f"[green]✓ {result.get('message', 'Text copied!')}[/green]")
                console.print()
                console.print("[dim]After checking, come back here and press Enter.[/dim]")
                input("\nPress Enter to continue...")
                continue

            # API check
            from rich.status import Status

            with Status("[bold cyan]Checking AI detection...[/bold cyan]", spinner="dots") as status:
                try:
                    from ai_detector import run_detection_for_submission
                    results = run_detection_for_submission(submission_dir, force=True)
                except Exception as e:
                    results = {"error": str(e)}

            if results and "services" in results:
                console.print()
                console.print("[bold]AI Detection Results:[/bold]")
                console.print()

                highest_score = 0
                for service, data in results["services"].items():
                    score = data.get("score")
                    status = data.get("status", "unknown")

                    if score is not None:
                        highest_score = max(highest_score, score)
                        if score < 20:
                            color = "green"
                            verdict = "Looks human!"
                        elif score < 50:
                            color = "yellow"
                            verdict = "Some AI detected"
                        else:
                            color = "red"
                            verdict = "High AI probability"

                        console.print(f"  [{color}]{service}:[/{color}] {score:.0f}% AI - {verdict}")
                    else:
                        console.print(f"  [dim]{service}: {status}[/dim]")

                console.print()

                # Offer humanization if score is high
                if highest_score >= 30:
                    console.print("[bold yellow]Score is high. Would you like to humanize the text?[/bold yellow]")
                    console.print()
                    console.print("  [cyan]1[/cyan]) Humanize text (rewrite to reduce AI detection)")
                    console.print("  [cyan]0[/cyan]) Skip for now")
                    console.print()

                    humanize_choice = Prompt.ask("Select", choices=["0", "1"], default="1")

                    if humanize_choice == "1":
                        console.print()

                        from ai_detector import humanize_text, check_zerogpt_api

                        with Status("[bold cyan]Humanizing text with Claude...[/bold cyan]", spinner="dots") as status:
                            humanize_result = humanize_text(text)

                        if humanize_result.get("success"):
                            rewritten = humanize_result["rewritten"]

                            # Save the humanized version with matching name
                            base_name = source_file.replace(".md", "")
                            humanized_filename = f"{base_name}_humanized.md"
                            humanized_path = submission_dir / humanized_filename
                            with open(humanized_path, "w") as f:
                                f.write(rewritten)

                            console.print(f"[green]✓ Humanized version saved to: {humanized_filename}[/green]")
                            console.print()

                            # Re-check the humanized version
                            with Status("[bold cyan]Re-checking humanized version...[/bold cyan]", spinner="dots") as status:
                                new_result = check_zerogpt_api(rewritten)
                                new_score = new_result.get("score")

                            # Save the humanized score to a separate cache file
                            if new_score is not None:
                                import json
                                from datetime import datetime
                                humanized_cache = {
                                    "checked_at": datetime.now().isoformat(),
                                    "services": {"zerogpt": new_result}
                                }
                                cache_filename = f"ai_check_{base_name}_humanized.json"
                                with open(submission_dir / cache_filename, "w") as f:
                                    json.dump(humanized_cache, f, indent=2)

                            console.print()
                            console.print("[bold]Before/After:[/bold]")
                            console.print(f"  Original:  [red]{highest_score:.0f}%[/red] AI")
                            if new_score is not None:
                                if new_score < 20:
                                    console.print(f"  Humanized: [green]{new_score:.0f}%[/green] AI ✓")
                                elif new_score < highest_score:
                                    console.print(f"  Humanized: [yellow]{new_score:.0f}%[/yellow] AI (improved)")
                                else:
                                    console.print(f"  Humanized: [yellow]{new_score:.0f}%[/yellow] AI")
                            else:
                                console.print(f"  Humanized: [dim]Could not re-check[/dim]")

                            console.print()
                            console.print("[dim]Review draft_humanized.md before using.[/dim]")
                        else:
                            console.print(f"[red]Could not humanize: {humanize_result.get('error')}[/red]")
                else:
                    console.print("[dim]Tip: Scores under 20% are generally safe.[/dim]")
            else:
                console.print("[yellow]Could not complete AI detection. Check your internet connection.[/yellow]")

            input("\nPress Enter to continue...")
        elif choice == "3":
            # View requirements
            req_file = assignment["path"] / "requirements.md"
            if req_file.exists():
                with open(req_file) as f:
                    content = f.read()
                console.print()
                console.print(Panel(Markdown(content), title="Requirements", border_style="cyan"))
            else:
                console.print("[yellow]No requirements file found.[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "4":
            # View rubric
            rubric_file = assignment["path"] / "rubric.md"
            if rubric_file.exists():
                with open(rubric_file) as f:
                    content = f.read()
                console.print()
                console.print(Panel(Markdown(content), title="Grading Rubric", border_style="green"))
            else:
                console.print("[yellow]No rubric found for this assignment.[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "5":
            # View course materials
            modules = find_relevant_modules(assignment)
            if modules:
                console.print()
                console.print("[bold]Available Course Materials:[/bold]")
                console.print()
                for i, mod in enumerate(modules, 1):
                    console.print(f"  [cyan]{i}[/cyan]) {mod['name']}")
                console.print(f"  [cyan]0[/cyan]) Back")
                console.print()

                mod_choice = Prompt.ask("Select module to view", default="0")
                try:
                    idx = int(mod_choice)
                    if 1 <= idx <= len(modules):
                        with open(modules[idx-1]['path']) as f:
                            content = f.read()
                        console.print()
                        console.print(Panel(Markdown(content), title=modules[idx-1]['name'], border_style="magenta"))
                except:
                    pass
            else:
                console.print("[yellow]No course materials found. Run sync to fetch module content.[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "7":
            # Open in browser
            import webbrowser
            a_file = assignment["path"] / "assignment.json"
            if a_file.exists():
                with open(a_file) as f:
                    a_info = json.load(f)
                url = a_info.get("url")
                if url:
                    webbrowser.open(url)
                    console.print(f"[green]Opened in browser![/green]")
                else:
                    console.print("[yellow]No URL found for this assignment.[/yellow]")
            input("\nPress Enter to continue...")
        elif choice == "t":
            # Show tool setup guide
            show_tool_status()
            show_tool_setup_guide()
            input("Press Enter to continue...")


def work_on_assignment():
    """Select and prepare to work on an assignment."""
    assignment = view_assignments()

    if not assignment:
        return False

    # Save as active assignment
    settings = load_settings()
    settings["active_assignment"] = {
        "name": assignment["name"],
        "course": assignment["course"],
        "path": str(assignment["path"]),
        "due_at": assignment["due_at"].isoformat(),
    }
    save_settings(settings)

    # Show work menu
    show_work_menu(assignment)
    return False


def show_settings():
    """Show settings menu."""
    console.print()
    console.print("[bold]Settings[/bold]")
    console.print()
    console.print(f"  Data directory: [dim]{DATA_DIR}[/dim]")
    console.print(f"  Session file: [dim]{SESSION_FILE}[/dim]")

    # Show tool status
    show_tool_status()

    console.print("[bold]Options:[/bold]")
    console.print()
    console.print("  [cyan]1[/cyan]) View tool setup guide")
    console.print("  [cyan]2[/cyan]) Clear session (logout)")
    console.print("  [cyan]0[/cyan]) Back to main menu")
    console.print()

    choice = Prompt.ask("Select", choices=["0", "1", "2"], default="0")

    if choice == "1":
        show_tool_setup_guide()
        input("Press Enter to continue...")
    elif choice == "2":
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
            console.print("[green]Session cleared. You'll need to log in again.[/green]")
        else:
            console.print("[dim]No session to clear.[/dim]")
        input("\nPress Enter to continue...")


def show_first_run_guide():
    """Show guide for first-time users."""
    console.print()
    console.print(Panel(
        "[bold]Welcome to Canvas Completer![/bold]\n\n"
        "I'm your rubber duck for homework - here to help you debug\n"
        "your way through assignments!\n\n"
        "[bold]Here's how to get started:[/bold]\n\n"
        "1. [cyan]Sync your courses[/cyan] — This will open a browser window\n"
        "   where you'll log in to Canvas with your Northwestern SSO.\n\n"
        "2. [cyan]View your assignments[/cyan] — After syncing, you'll see all\n"
        "   your courses, syllabi, and upcoming homework.\n\n"
        "3. [cyan]Work on assignments[/cyan] — Select an assignment and open it\n"
        "   in Claude Code or Cursor to get AI help.\n\n"
        "[dim]Your session will be saved so you won't need to log in every time.[/dim]",
        title="Getting Started",
        border_style="cyan",
    ))
    console.print()

    # Check for AI tools
    tools = get_tool_status()
    if not tools["claude"] and not tools["cursor"]:
        console.print("[yellow]Note:[/yellow] No AI coding tools detected.")
        console.print("[dim]For the best experience, install Claude Code or Cursor.[/dim]")
        show_tool_setup_guide()

    if Confirm.ask("Ready to sync your courses?", default=True):
        return "sync"
    return None


def show_wait_screen(assignment_name, tool_name="Claude Code"):
    """Show a waiting screen while AI tool runs in split pane."""
    duck = """[yellow]       __
     >(o )___
      ( .__> /
       `---'[/yellow]
      [cyan]~~[/cyan][yellow]**[/yellow][cyan]~~[/cyan]"""

    console.clear()
    console.print()
    console.print(Panel(
        f"{duck}\n\n"
        f"[bold]{tool_name} is running in the right pane →[/bold]\n\n"
        f"[dim]Assignment: {assignment_name}[/dim]\n\n"
        "[bold]When you're done:[/bold]\n"
        f"  • Type [cyan]/exit[/cyan] in {tool_name}, or\n"
        "  • Press [cyan]Ctrl+B[/cyan] then [cyan]x[/cyan] to close that pane\n\n"
        "[dim]Press Enter here when done to exit.[/dim]",
        title="Working on Assignment",
        border_style="cyan",
        expand=True,  # Expand to fill available width
    ))
    console.print()
    input("Press Enter when done...")


def main():
    """Main entry point."""
    # Handle command line arguments
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "sync":
            run_sync()
            return 0
        elif cmd == "logout":
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
                console.print("Logged out.")
            return 0
        elif cmd == "--wait":
            # Wait mode - show waiting screen for tmux split
            assignment_name = sys.argv[2] if len(sys.argv) > 2 else "Assignment"
            tool_name = sys.argv[3] if len(sys.argv) > 3 else "Claude Code"
            show_wait_screen(assignment_name, tool_name)
            return 0
        elif cmd == "--help":
            console.print("Usage: python main.py [command]")
            console.print()
            console.print("Commands:")
            console.print("  (none)    Interactive mode")
            console.print("  sync      Sync courses and assignments")
            console.print("  logout    Clear saved session")
            return 0

    # Interactive mode
    show_welcome()

    courses = get_sync_status()

    # First run experience
    if not courses and not is_authenticated():
        action = show_first_run_guide()
        if action == "sync":
            run_sync()

    # Main loop - course-first navigation
    show_archived = False
    while True:
        console.clear()
        show_welcome()

        # Check authentication
        if not is_authenticated():
            console.print("[red]●[/red] Not authenticated")
            console.print()
            if Confirm.ask("Would you like to sync your courses?", default=True):
                run_sync()
            continue

        # Show course selection
        result = show_course_selection(show_archived=show_archived)

        # Handle toggle archived
        if isinstance(result, tuple) and result[0] == "toggle_archived":
            show_archived = result[1]
            continue

        if result == "quit":
            console.print()
            console.print("[yellow]   __[/yellow]")
            console.print("[yellow] >(o )  [/yellow][dim]Quack! Good luck with your assignments![/dim]")
            console.print("[yellow]  ~~[/yellow]")
            console.print()
            break
        elif result == "sync":
            run_sync()
            input("\nPress Enter to continue...")
        elif result is None:
            # No courses, prompt to sync
            console.print("[yellow]No courses found.[/yellow]")
            if Confirm.ask("Would you like to sync your courses?", default=True):
                run_sync()
        else:
            # Selected a course - show course view
            show_course_view(result)

    return 0


if __name__ == "__main__":
    try:
        exit(main())
    except KeyboardInterrupt:
        console.print()
        console.print()
        console.print("[yellow]   __[/yellow]")
        console.print("[yellow] >(o )  [/yellow][dim]Quack! Caught you ducking out early![/dim]")
        console.print("[yellow]  ~~[/yellow]")
        console.print()
        exit(0)
