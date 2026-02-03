#!/usr/bin/env python3
"""
AI Detection Checker for Canvas Completer
Runs text through multiple AI detection services to check for AI-generated content.
"""

import json
import time
import hashlib
from pathlib import Path
from datetime import datetime


def get_text_hash(text):
    """Get hash of text content for change detection."""
    return hashlib.md5(text.encode()).hexdigest()


def load_cached_results(submission_dir):
    """Load cached AI detection results."""
    cache_file = Path(submission_dir) / "ai_check.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                return json.load(f)
        except:
            pass
    return None


def save_cached_results(submission_dir, results):
    """Save AI detection results to cache."""
    cache_file = Path(submission_dir) / "ai_check.json"
    with open(cache_file, "w") as f:
        json.dump(results, f, indent=2)


def needs_recheck(submission_dir):
    """Check if files have changed since last AI detection scan."""
    submission_dir = Path(submission_dir)
    cached = load_cached_results(submission_dir)

    if not cached:
        return True

    # Check if any submission files have changed
    for filename in ["draft.md", "final.md"]:
        filepath = submission_dir / filename
        if filepath.exists():
            with open(filepath) as f:
                current_hash = get_text_hash(f.read())

            cached_hash = cached.get("file_hashes", {}).get(filename)
            if cached_hash != current_hash:
                return True

    return False


def check_zerogpt(text, page):
    """Check text using ZeroGPT web interface."""
    try:
        page.goto("https://www.zerogpt.com/", timeout=60000)
        time.sleep(2)  # Let page settle

        # Find and fill the textarea
        textarea = page.wait_for_selector("textarea", timeout=15000)
        textarea.fill(text[:15000])  # ZeroGPT has character limits

        # Click detect button - try multiple selectors
        time.sleep(1)
        detect_btn = page.query_selector("button:has-text('Detect')") or \
                     page.query_selector("button[type='submit']") or \
                     page.query_selector(".detect-btn") or \
                     page.query_selector("button.btn-primary")
        if detect_btn:
            detect_btn.click()
        else:
            # Try pressing Enter in textarea
            textarea.press("Enter")

        # Wait for results
        time.sleep(5)
        page.wait_for_load_state("domcontentloaded", timeout=30000)

        # Try to find the result percentage
        # ZeroGPT shows results in various formats
        result_selectors = [
            ".result-percentage",
            "[class*='percentage']",
            "[class*='result']",
            "text=/\\d+(\\.\\d+)?%/"
        ]

        for selector in result_selectors:
            try:
                element = page.query_selector(selector)
                if element:
                    text_content = element.text_content()
                    # Extract percentage
                    import re
                    match = re.search(r'(\d+(?:\.\d+)?)\s*%', text_content)
                    if match:
                        return {
                            "score": float(match.group(1)),
                            "status": "success",
                            "raw": text_content
                        }
            except:
                continue

        # Try to get any visible result text
        body_text = page.content()
        import re
        matches = re.findall(r'(\d+(?:\.\d+)?)\s*%\s*(?:AI|generated|GPT)', body_text, re.IGNORECASE)
        if matches:
            return {
                "score": float(matches[0]),
                "status": "success",
                "raw": matches[0] + "%"
            }

        return {"score": None, "status": "could not parse result"}

    except Exception as e:
        return {"score": None, "status": f"error: {str(e)[:50]}"}


def get_gptzero_session(debug=False):
    """Get an anonymous session token from GPTZero using Playwright."""
    import requests

    try:
        from playwright.sync_api import sync_playwright

        print("    Getting GPTZero session...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # Visit the app page to trigger anonymous auth
            page.goto("https://app.gptzero.me/", timeout=30000)

            # Wait longer for JS/Supabase auth to complete
            time.sleep(5)

            # Try to wait for the accessToken cookie specifically
            for _ in range(10):  # Wait up to 10 more seconds
                cookies = context.cookies()
                cookie_names = [c["name"] for c in cookies]
                if "accessToken4" in cookie_names or any("accessToken" in n for n in cookie_names):
                    break
                time.sleep(1)

            # Get final cookies
            cookies = context.cookies()
            browser.close()

        if debug:
            print(f"    Got {len(cookies)} cookies:")
            for c in cookies:
                val_preview = c["value"][:30] + "..." if len(c["value"]) > 30 else c["value"]
                print(f"      - {c['name']}: {val_preview}")

        # Check for required cookies
        cookie_names = [c["name"] for c in cookies]
        has_access_token = any("accessToken" in n for n in cookie_names)
        has_csrf = any("csrf" in n.lower() for n in cookie_names)

        if debug:
            print(f"    Has access token: {has_access_token}")
            print(f"    Has CSRF token: {has_csrf}")

        if not has_access_token:
            print("    Warning: No access token found in cookies")

        # Create a requests session with these cookies
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

        for cookie in cookies:
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", "").lstrip("."),
                path=cookie.get("path", "/"),
            )

        return session

    except Exception as e:
        print(f"    Could not get GPTZero session: {e}")
        return None


def check_gptzero_api(text, session=None, debug=False):
    """Check text using GPTZero API."""
    import requests
    import uuid

    try:
        # Get a session with auth cookies if not provided
        if session is None:
            session = get_gptzero_session(debug=debug)
        if not session:
            return {"score": None, "status": "could not establish session"}

        # GPTZero API endpoint
        url = "https://api.gptzero.me/v3/ai/text"

        # Generate a scan ID
        scan_id = str(uuid.uuid4())

        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": "https://app.gptzero.me",
            "referer": "https://app.gptzero.me/",
            "x-gptzero-platform": "webapp",
            "x-page": "/",
        }

        payload = {
            "scanId": scan_id,
            "multilingual": True,
            "document": text[:10000],  # Limit text length
            "interpretability_required": False,
        }

        response = session.post(url, json=payload, headers=headers, timeout=30)

        if debug:
            print(f"    Response status: {response.status_code}")
            print(f"    Response headers: {dict(response.headers)}")
            try:
                print(f"    Response body preview: {response.text[:500]}")
            except:
                pass

        if response.ok:
            data = response.json()

            # Extract the AI probability score
            documents = data.get("documents", [])
            if documents:
                doc = documents[0]
                # completely_generated_prob is the main AI score
                ai_prob = doc.get("completely_generated_prob")
                if ai_prob is not None:
                    return {
                        "score": round(ai_prob * 100, 1),
                        "status": "success",
                        "details": {
                            "average_perplexity": doc.get("average_generated_prob"),
                            "sentences_flagged": len([s for s in doc.get("sentences", []) if s.get("generated_prob", 0) > 0.5])
                        }
                    }

            return {"score": None, "status": "could not parse response", "raw": data}
        else:
            # Try to get error details
            try:
                error_data = response.json()
                error_msg = error_data.get("error", response.status_code)
            except:
                error_msg = response.status_code
            return {"score": None, "status": f"API error: {error_msg}"}

    except Exception as e:
        return {"score": None, "status": f"error: {str(e)[:50]}"}


def check_gptzero(text, page=None):
    """Check text using GPTZero (API-based)."""
    return check_gptzero_api(text)


def check_zerogpt_api(text):
    """Check text using ZeroGPT API."""
    import requests

    try:
        url = "https://api.zerogpt.com/api/detect/detectText"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Origin": "https://www.zerogpt.com",
            "Referer": "https://www.zerogpt.com/",
        }

        payload = {
            "input_text": text[:15000],
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.ok:
            data = response.json()

            if data.get("success"):
                # ZeroGPT returns fakePercentage
                fake_pct = data.get("data", {}).get("fakePercentage")
                if fake_pct is not None:
                    return {
                        "score": float(fake_pct),
                        "status": "success",
                        "details": {
                            "is_human": data.get("data", {}).get("isHuman"),
                            "feedback": data.get("data", {}).get("feedback"),
                        }
                    }

            return {"score": None, "status": "could not parse response"}
        else:
            return {"score": None, "status": f"API error: {response.status_code}"}

    except Exception as e:
        return {"score": None, "status": f"error: {str(e)[:50]}"}


def humanize_text(text):
    """Rewrite text to sound more human and less AI-generated using Claude Code CLI."""
    import subprocess
    import tempfile

    prompt = """Rewrite the following text to sound more human and natural, as if written by a real student. Output ONLY the rewritten text, nothing else.

WRITING STYLE:
- Write as a B+/A- student - good but not perfect
- Occasionally start sentences with "And" or "But"
- Use contractions naturally (don't, isn't, it's, we'll)
- Include 1-2 slightly awkward phrasings that a human wouldn't catch
- Vary sentence lengths - some short, some longer
- Sound like a student explaining to a classmate, not a textbook

AVOID THESE AI TELLS:
- "delve into", "tapestry", "multifaceted", "in today's society"
- "It's important to note", "Furthermore", "Moreover", "Additionally"
- "In conclusion", "To summarize", "As mentioned above"
- Overly formal transitions between ideas

FORMATTING (THIS IS CRITICAL):
- Convert bullet points and numbered lists into regular prose paragraphs
- Remove excessive bold and italics - students rarely use these
- Don't use em dashes (—) - use commas or periods instead
- Avoid perfect parallel structure in lists
- Vary paragraph lengths - not all the same size
- Don't add headers like "Introduction" or "Conclusion"
- Avoid colon introductions ("There are three points:")
- Write in flowing paragraphs, not choppy organized sections
- If the original has bullets, weave those points into sentences
- A real student paper is often less organized, more conversational

KEEP:
- The same core meaning and arguments
- Any citations (but format them slightly imperfectly)
- The approximate length

Output ONLY the rewritten text - no explanations, no preamble, no "Here's the rewritten version:".

TEXT TO REWRITE:

""" + text

    try:
        # Check if claude CLI is available
        result = subprocess.run(
            ["which", "claude"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return {
                "success": False,
                "error": "Claude Code CLI not found. Install it with: npm install -g @anthropic-ai/claude-code"
            }

        # Use claude CLI with --print flag to get output directly
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout
        )

        if result.returncode == 0:
            rewritten = result.stdout.strip()

            # Clean up any potential preamble Claude might add
            # Look for common patterns and skip them
            lines = rewritten.split('\n')
            start_idx = 0
            for i, line in enumerate(lines):
                line_lower = line.lower().strip()
                if line_lower.startswith(('here', 'i\'ve', 'below', 'the rewritten', 'rewritten version')):
                    start_idx = i + 1
                    continue
                if line.strip() == '---' or line.strip() == '':
                    start_idx = i + 1
                    continue
                break

            rewritten = '\n'.join(lines[start_idx:]).strip()

            return {
                "success": True,
                "original": text,
                "rewritten": rewritten,
                "original_length": len(text),
                "rewritten_length": len(rewritten),
            }
        else:
            return {
                "success": False,
                "error": f"Claude CLI error: {result.stderr[:100] if result.stderr else 'Unknown error'}"
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Claude CLI timed out after 2 minutes"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def open_detector_with_clipboard(text, service="zerogpt"):
    """Copy text to clipboard and open detector website."""
    import subprocess
    import webbrowser

    urls = {
        "zerogpt": "https://www.zerogpt.com/",
        "gptzero": "https://gptzero.me/",
        "scribbr": "https://www.scribbr.com/ai-detector/",
    }

    try:
        # Copy text to clipboard (macOS)
        process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
        process.communicate(text.encode('utf-8'))

        # Open the website
        url = urls.get(service, urls["zerogpt"])
        webbrowser.open(url)

        return {
            "status": "opened",
            "message": f"Text copied to clipboard. Paste it into {service} to check."
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def check_scribbr(text, page):
    """Check text using Scribbr AI detector."""
    try:
        page.goto("https://www.scribbr.com/ai-detector/", timeout=60000)
        time.sleep(3)

        # Handle cookie consent if present
        try:
            accept_btn = page.query_selector("button:has-text('Accept'), button:has-text('OK'), button:has-text('Got it')")
            if accept_btn:
                accept_btn.click()
                time.sleep(1)
        except:
            pass

        # Find textarea
        textarea = page.query_selector("textarea") or \
                   page.query_selector("[contenteditable='true']")

        if textarea:
            textarea.click()
            textarea.fill(text[:10000])
        else:
            return {"score": None, "status": "could not find text input"}

        # Find and click detect button
        time.sleep(1)
        detect_btn = page.query_selector("button:has-text('Detect')") or \
                     page.query_selector("button:has-text('Check')") or \
                     page.query_selector("button:has-text('Scan')") or \
                     page.query_selector("button:has-text('Analyze')") or \
                     page.query_selector("button[type='submit']")
        if detect_btn:
            detect_btn.click()

        # Wait for results
        time.sleep(8)
        page.wait_for_load_state("domcontentloaded", timeout=30000)

        # Parse results
        body_text = page.content()
        import re

        matches = re.findall(r'(\d+(?:\.\d+)?)\s*%', body_text)
        if matches:
            # Usually the AI percentage is prominent
            return {
                "score": float(matches[0]),
                "status": "success"
            }

        return {"score": None, "status": "could not parse result"}

    except Exception as e:
        return {"score": None, "status": f"error: {str(e)[:50]}"}


def run_ai_detection(text, services=None):
    """Run AI detection on text using multiple services.

    Args:
        text: The text to check
        services: List of services to use, or None for default

    Returns:
        Dict with results from each service
    """
    if services is None:
        services = ["zerogpt"]  # Default to ZeroGPT API

    results = {
        "checked_at": datetime.now().isoformat(),
        "text_hash": get_text_hash(text),
        "text_length": len(text),
        "services": {}
    }

    # API-based services (no browser needed) - these are reliable
    api_services = {
        "zerogpt": check_zerogpt_api,
    }

    # Browser-based services (less reliable, only used if no API available)
    browser_only_services = ["scribbr"]

    # Run API-based checks
    for service in services:
        if service in api_services:
            print(f"    Checking {service} (API)...")
            try:
                results["services"][service] = api_services[service](text)
            except Exception as e:
                results["services"][service] = {"score": None, "status": f"error: {str(e)[:50]}"}

    # Run browser-based checks only for services that don't have API
    browser_needed = [s for s in services if s in browser_only_services and s not in results["services"]]
    if browser_needed:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                )

                browser_funcs = {
                    "scribbr": check_scribbr,
                }

                for service in browser_needed:
                    if service in browser_funcs:
                        print(f"    Checking {service} (browser)...")
                        page = context.new_page()
                        try:
                            results["services"][service] = browser_funcs[service](text, page)
                        except Exception as e:
                            results["services"][service] = {"score": None, "status": f"error: {str(e)[:50]}"}
                        finally:
                            page.close()

                browser.close()

        except Exception as e:
            for service in browser_needed:
                if service not in results["services"]:
                    results["services"][service] = {"score": None, "status": f"browser error: {str(e)[:30]}"}

    return results


def run_ai_detection_full(text):
    """Run AI detection with ZeroGPT API."""
    return run_ai_detection(text, services=["zerogpt"])


def run_ai_detection_quick(text):
    """Quick AI detection with ZeroGPT API."""
    return run_ai_detection(text, services=["zerogpt"])


def run_detection_for_submission(submission_dir, force=False):
    """Run AI detection for a submission folder.

    Args:
        submission_dir: Path to submission folder
        force: Run even if files haven't changed

    Returns:
        Detection results dict
    """
    submission_dir = Path(submission_dir)

    # Check if we need to run
    if not force and not needs_recheck(submission_dir):
        return load_cached_results(submission_dir)

    # Get text from submission files
    text_parts = []
    file_hashes = {}

    for filename in ["final.md", "draft.md"]:  # Prefer final over draft
        filepath = submission_dir / filename
        if filepath.exists():
            with open(filepath) as f:
                content = f.read()
            text_parts.append(content)
            file_hashes[filename] = get_text_hash(content)
            break  # Only check one file

    if not text_parts:
        return {"error": "No submission files found"}

    text = text_parts[0]

    # Run detection
    results = run_ai_detection(text)
    results["file_hashes"] = file_hashes

    # Cache results
    save_cached_results(submission_dir, results)

    return results


def format_detection_results(results):
    """Format detection results for display."""
    if not results or results.get("error"):
        return None, results.get("error", "No results")

    services = results.get("services", {})
    if not services:
        return None, "No detection services ran"

    parts = []
    all_good = True

    for service, data in services.items():
        score = data.get("score")
        if score is not None:
            # Color based on score
            if score < 20:
                color = "green"
                symbol = "✓"
            elif score < 50:
                color = "yellow"
                symbol = "◐"
                all_good = False
            else:
                color = "red"
                symbol = "✗"
                all_good = False

            parts.append(f"[{color}]{service} {score:.0f}%[/{color}]")
        else:
            parts.append(f"[dim]{service} --[/dim]")

    # Format timestamp
    checked_at = results.get("checked_at")
    if checked_at:
        try:
            dt = datetime.fromisoformat(checked_at)
            now = datetime.now()
            diff = now - dt

            if diff.days > 0:
                time_ago = f"{diff.days}d ago"
            elif diff.seconds > 3600:
                time_ago = f"{diff.seconds // 3600}h ago"
            elif diff.seconds > 60:
                time_ago = f"{diff.seconds // 60}m ago"
            else:
                time_ago = "just now"
        except:
            time_ago = "unknown"
    else:
        time_ago = "unknown"

    status_line = " | ".join(parts)
    return status_line, time_ago


def debug_check_zerogpt(text, output_dir=None):
    """Debug version that saves screenshots at each step."""
    from playwright.sync_api import sync_playwright
    from pathlib import Path

    if output_dir is None:
        output_dir = Path.home() / ".config" / "canvas-completer" / "debug"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Debug output will be saved to: {output_dir}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            print("1. Loading ZeroGPT...")
            page.goto("https://www.zerogpt.com/", timeout=60000)
            time.sleep(3)
            page.screenshot(path=str(output_dir / "01_loaded.png"))
            print(f"   Screenshot saved: 01_loaded.png")

            print("2. Looking for textarea...")
            textarea = page.query_selector("textarea")
            if textarea:
                print(f"   Found textarea")
                textarea.fill(text[:1000])
                time.sleep(1)
                page.screenshot(path=str(output_dir / "02_filled.png"))
                print(f"   Screenshot saved: 02_filled.png")
            else:
                print("   ERROR: No textarea found")
                # Save page HTML for debugging
                with open(output_dir / "page.html", "w") as f:
                    f.write(page.content())
                print(f"   Page HTML saved to: page.html")

            print("3. Looking for detect button...")
            buttons = page.query_selector_all("button")
            print(f"   Found {len(buttons)} buttons:")
            for i, btn in enumerate(buttons):
                btn_text = btn.text_content().strip()[:50]
                print(f"     {i}: '{btn_text}'")

            detect_btn = page.query_selector("button:has-text('Detect')")
            if detect_btn:
                print("   Found 'Detect' button, clicking...")
                detect_btn.click()
                time.sleep(5)
                page.screenshot(path=str(output_dir / "03_clicked.png"))
                print(f"   Screenshot saved: 03_clicked.png")
            else:
                print("   ERROR: No detect button found")

            print("4. Waiting for results...")
            time.sleep(5)
            page.screenshot(path=str(output_dir / "04_results.png"))
            print(f"   Screenshot saved: 04_results.png")

            print("5. Page content preview:")
            content = page.content()
            # Look for percentage patterns
            import re
            percentages = re.findall(r'(\d+(?:\.\d+)?)\s*%', content)
            print(f"   Found percentages: {percentages[:10]}")

            # Save full HTML
            with open(output_dir / "final_page.html", "w") as f:
                f.write(content)
            print(f"   Full HTML saved to: final_page.html")

        except Exception as e:
            print(f"ERROR: {e}")
            page.screenshot(path=str(output_dir / "error.png"))
        finally:
            browser.close()

    print(f"\nDebug complete! Check screenshots in: {output_dir}")


if __name__ == "__main__":
    import sys

    sample_text = """
    This is a sample essay about machine learning. Machine learning is a subset
    of artificial intelligence that enables systems to learn and improve from
    experience without being explicitly programmed. The field has grown
    significantly in recent years due to advances in computing power and data
    availability. Deep learning, a subset of machine learning, has particularly
    revolutionized fields like computer vision and natural language processing.
    """

    if len(sys.argv) > 1 and sys.argv[1] == "--debug":
        # Debug mode for browser-based checks
        text = sample_text
        if len(sys.argv) > 2:
            with open(sys.argv[2]) as f:
                text = f.read()
        debug_check_zerogpt(text)

    elif len(sys.argv) > 1 and sys.argv[1] == "--test":
        # Quick test of ZeroGPT API
        print("Testing ZeroGPT API...")
        print()
        result = check_zerogpt_api(sample_text)

        if result.get("score") is not None:
            score = result["score"]
            if score < 20:
                verdict = "Looks human! ✓"
            elif score < 50:
                verdict = "Some AI detected"
            else:
                verdict = "High AI probability"
            print(f"Score: {score}% AI detected - {verdict}")
            print(f"Feedback: {result.get('details', {}).get('feedback', 'N/A')}")
        else:
            print(f"Error: {result.get('status')}")

    elif len(sys.argv) > 1:
        # Check a file
        with open(sys.argv[1]) as f:
            text = f.read()
        print(f"Running AI detection on {sys.argv[1]}...")
        print(f"Text length: {len(text)} characters")
        print()
        results = run_ai_detection(text)
        print(json.dumps(results, indent=2))

    else:
        print("AI Detection Tool")
        print("=" * 40)
        print()
        print("Usage:")
        print("  python ai_detector.py <file.md>   - Check a file")
        print("  python ai_detector.py --test      - Quick API test")
        print("  python ai_detector.py --debug     - Debug browser mode")
        print()
        print("Running quick test...")
        print()
        result = check_zerogpt_api(sample_text)
        if result.get("score") is not None:
            print(f"✓ ZeroGPT API working! Score: {result['score']}% AI detected")
        else:
            print(f"✗ ZeroGPT API error: {result.get('status')}")
