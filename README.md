# 🎓 Canvas Completer

A CLI tool to help manage Canvas LMS assignments. Syncs your courses, assignments, and course materials locally for easy access and AI-assisted homework help.

## ✨ Features

- **📚 Course Sync** — Automatically fetches all your active courses, syllabi, and assignments
- **📅 Assignment Tracking** — View upcoming assignments with due dates and submission status
- **📄 Content Extraction** — Downloads and extracts content from PDFs, YouTube videos, Panopto recordings, and more
- **🤖 AI Integration** — Works with Claude Code or Cursor for AI-assisted assignment help
- **🔍 AI Detection** — Built-in AI detection checking to review written work
- **💾 Offline Access** — All course materials stored locally for offline reference

## 📋 Requirements

- Python 3.10+
- A Canvas LMS account at your school

## 🚀 Installation

### Option 1: pip (Recommended)

```bash
pip install canvas-completer
```

Then install the browser for authentication:
```bash
playwright install chromium
```

### Option 2: pipx (Isolated Environment)

```bash
pipx install canvas-completer
pipx runpip canvas-completer install playwright
playwright install chromium
```

### Option 3: From Source

```bash
git clone https://github.com/MillerMedia/canvas-completer.git
cd canvas-completer
pip install -e .
playwright install chromium
```

## ⚙️ Configuration

On first run, you'll be prompted to enter your school's Canvas URL. Examples:
- `https://canvas.instructure.com`
- `https://canvas.university.edu`
- `https://school.instructure.com`

Your configuration is stored in `~/.config/canvas-completer/`.

## 📖 Usage

### Interactive Mode (Recommended)

```bash
canvas-completer
```

This launches the interactive CLI where you can:
- 🔄 Sync your courses
- 📂 Browse assignments by course
- 📝 View assignment details and rubrics
- 🤖 Open assignments in Claude Code or Cursor for AI help

### Quick Commands

```bash
# Sync courses and assignments
canvas-completer sync

# Clear saved session (logout)
canvas-completer logout
```

## 📁 Data Storage

All synced data is stored locally at:
```
~/.config/canvas-completer/
├── config.json          # Your Canvas URL and token
├── session.json         # Browser session (for SSO login)
├── settings.json        # User preferences
└── data/
    └── courses/
        └── Course_Name/
            ├── course_info.json
            ├── syllabus.md
            ├── assignments/
            │   └── Assignment_Name/
            │       ├── assignment.json
            │       ├── requirements.md
            │       ├── rubric.md
            │       └── submission/
            └── modules/
                └── Module_Name/
                    └── content.md
```

## 🛠️ Optional Tools

For the best experience, install these AI coding assistants:

| Tool | Install | Description |
|------|---------|-------------|
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` | Recommended for AI help |
| **Cursor** | [cursor.com](https://cursor.com) | AI-powered code editor |
| **tmux** | `brew install tmux` | Enables split-pane view |

## 🔒 Privacy & Security

- Your Canvas token is stored locally with restricted file permissions (600)
- No data is sent to external servers (except Canvas and optional AI detection services)
- Session cookies are stored locally for convenience

## ❓ Troubleshooting

### "Session expired" errors
Run `canvas-completer logout` then sync again to re-authenticate.

### Browser doesn't open for login
Make sure Playwright browsers are installed: `playwright install chromium`

### Can't find your Canvas URL
Check the URL you use to access Canvas in your browser. It typically looks like `https://canvas.schoolname.edu` or `https://schoolname.instructure.com`.

## 📄 License

MIT License — See [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions welcome! Please open an issue or submit a pull request.

---

<p align="center">
  <i>Made with 🦆 by <a href="https://github.com/MillerMedia">MillerMedia</a></i>
</p>
