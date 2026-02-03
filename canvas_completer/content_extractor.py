#!/usr/bin/env python3
"""
Content Extractor for Canvas Completer
Extracts and processes content from various sources (PDFs, videos, web pages).
"""

import re
import json
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def extract_youtube_id(url):
    """Extract YouTube video ID from various URL formats."""
    parsed = urlparse(url)

    if 'youtube.com' in parsed.netloc:
        if parsed.path == '/watch':
            return parse_qs(parsed.query).get('v', [None])[0]
        elif parsed.path.startswith('/embed/'):
            return parsed.path.split('/')[2]
    elif 'youtu.be' in parsed.netloc:
        return parsed.path[1:]

    return None


def extract_panopto_id(url):
    """Extract Panopto video ID from URL."""
    parsed = urlparse(url)

    # Format: .../Viewer.aspx?id=VIDEO_ID
    if 'panopto' in parsed.netloc.lower():
        video_id = parse_qs(parsed.query).get('id', [None])[0]
        if video_id:
            return video_id, parsed.netloc

    return None, None


def get_panopto_transcript(video_id, panopto_host, session=None):
    """Try to get transcript/captions from Panopto video."""
    try:
        import requests

        # Panopto caption delivery endpoint
        captions_url = f"https://{panopto_host}/Panopto/Pages/Viewer/DeliveryInfo.aspx"

        params = {
            'deliveryId': video_id,
            'responseType': 'json',
        }

        # Use provided session or create new one
        req_session = session if session else requests.Session()

        response = req_session.get(captions_url, params=params, timeout=30)

        if response.ok:
            try:
                data = response.json()

                # Look for captions in the delivery info
                delivery = data.get('Delivery', {})

                # Try to get captions/transcripts
                captions = delivery.get('Captions', [])
                if captions:
                    # Fetch the first available caption track
                    for caption in captions:
                        caption_url = caption.get('Url')
                        if caption_url:
                            cap_response = req_session.get(caption_url, timeout=30)
                            if cap_response.ok:
                                # Parse VTT/SRT format to plain text
                                return parse_caption_file(cap_response.text)

                # Try PodcastStreams for audio transcripts
                streams = delivery.get('PodcastStreams', [])
                for stream in streams:
                    if stream.get('HasTranscript'):
                        # There's a transcript available
                        pass

                # Get video title at minimum
                title = delivery.get('SessionName', 'Panopto Video')
                return f"[Panopto Video: {title}]\n[Captions not available or require authentication]"

            except (ValueError, KeyError):
                pass

        return "[Panopto video - could not extract transcript]"

    except Exception as e:
        return f"[Panopto video - error: {e}]"


def parse_caption_file(content):
    """Parse VTT or SRT caption file to plain text."""
    lines = content.split('\n')
    text_lines = []

    for line in lines:
        line = line.strip()

        # Skip VTT header
        if line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue

        # Skip timestamp lines (00:00:00.000 --> 00:00:00.000)
        if '-->' in line:
            continue

        # Skip cue identifiers (numbers or cue IDs)
        if re.match(r'^\d+$', line) or re.match(r'^[a-f0-9-]+$', line):
            continue

        # Skip empty lines
        if not line:
            continue

        # Remove HTML tags from captions
        line = re.sub(r'<[^>]+>', '', line)

        if line:
            text_lines.append(line)

    return ' '.join(text_lines)


def get_youtube_transcript(video_id):
    """Get transcript from YouTube video."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

        # Combine all transcript segments
        full_text = []
        for segment in transcript_list:
            full_text.append(segment['text'])

        return ' '.join(full_text)
    except Exception as e:
        return f"[Could not extract transcript: {e}]"


def extract_pdf_text(pdf_path_or_bytes):
    """Extract text from a PDF file."""
    try:
        import logging
        import warnings
        from pypdf import PdfReader

        # Suppress pypdf warnings about malformed PDFs
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        warnings.filterwarnings("ignore", module="pypdf")

        if isinstance(pdf_path_or_bytes, bytes):
            # Check if this is actually a PDF (starts with %PDF)
            if not pdf_path_or_bytes.startswith(b'%PDF'):
                # Might be HTML error page or other content
                if b'<html' in pdf_path_or_bytes[:1000].lower() or b'<!doctype' in pdf_path_or_bytes[:1000].lower():
                    return "[Could not extract PDF: received HTML instead of PDF - authentication may have failed]"
                return "[Could not extract PDF: file does not appear to be a valid PDF]"
            import io
            reader = PdfReader(io.BytesIO(pdf_path_or_bytes))
        else:
            reader = PdfReader(pdf_path_or_bytes)

        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

        return '\n\n'.join(text_parts)
    except Exception as e:
        return f"[Could not extract PDF text: {e}]"


def extract_zip_contents(zip_bytes, extract_dir):
    """Extract zip file and process contents."""
    import zipfile
    import io

    # Check if this is actually a zip file
    if not zip_bytes.startswith(b'PK'):
        if b'<html' in zip_bytes[:1000].lower() or b'<!doctype' in zip_bytes[:1000].lower():
            return "[Could not extract zip: received HTML instead of zip file - authentication may have failed]"
        return "[Could not extract zip: file does not appear to be a valid zip file]"

    extracted_content = []
    files_list = []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Create extraction directory
            extract_dir = Path(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)

            for file_info in zf.infolist():
                if file_info.is_dir():
                    continue

                filename = file_info.filename
                file_lower = filename.lower()

                # Extract the file
                try:
                    zf.extract(file_info, extract_dir)
                    extracted_path = extract_dir / filename
                    files_list.append(filename)

                    # Process based on file type
                    if file_lower.endswith('.pdf'):
                        pdf_text = extract_pdf_text(extracted_path)
                        if not pdf_text.startswith('[Could not'):
                            extracted_content.append(f"### {filename}\n\n{pdf_text}")

                    elif file_lower.endswith(('.py', '.r', '.ipynb', '.sql', '.js', '.java', '.cpp', '.c', '.h', '.sh', '.bat', '.ps1', '.yml', '.yaml')) or Path(filename).name.lower() in ('dockerfile', 'makefile', 'rakefile'):
                        # Code/config files - read and include
                        try:
                            with open(extracted_path, 'r', encoding='utf-8', errors='ignore') as f:
                                code = f.read()
                            if len(code) < 50000:  # Don't include huge files
                                ext = Path(filename).suffix[1:] if Path(filename).suffix else 'text'
                                extracted_content.append(f"### {filename}\n\n```{ext}\n{code}\n```")
                        except:
                            pass

                    elif file_lower.endswith(('.txt', '.md', '.csv', '.json', '.xml', '.html', '.rst', '.cfg', '.ini', '.toml')):
                        # Text/config files - read and include
                        try:
                            with open(extracted_path, 'r', encoding='utf-8', errors='ignore') as f:
                                text = f.read()
                            if len(text) < 50000:  # Don't include huge files
                                extracted_content.append(f"### {filename}\n\n{text}")
                        except:
                            pass

                    # Skip binary files (images, videos, etc.) but they're still extracted

                except Exception as e:
                    files_list.append(f"{filename} (extraction failed: {e})")

        # Build summary
        summary = f"**Extracted {len(files_list)} files:**\n"
        for f in files_list[:20]:  # Show first 20 files
            summary += f"- {f}\n"
        if len(files_list) > 20:
            summary += f"- ... and {len(files_list) - 20} more files\n"

        summary += f"\n**Location:** {extract_dir}\n"

        if extracted_content:
            summary += "\n---\n\n" + "\n\n---\n\n".join(extracted_content)

        return summary

    except zipfile.BadZipFile:
        return "[Could not extract: Invalid zip file]"
    except Exception as e:
        return f"[Could not extract zip: {e}]"


def extract_webpage_content(url, page=None):
    """Extract main content from a webpage."""
    try:
        if page:
            # Use Playwright page to fetch (handles auth)
            response = page.request.get(url)
            if response.ok:
                html = response.text()
            else:
                return f"[Could not fetch page: {response.status}]"
        else:
            import requests
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            html = response.text

        # Basic HTML to text conversion
        # Remove script and style tags
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Convert common elements
        html = re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'\n\n## \1\n\n', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<li[^>]*>(.*?)</li>', r'• \1\n', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove remaining tags
        text = re.sub(r'<[^>]+>', '', html)

        # Decode HTML entities
        from html import unescape
        text = unescape(text)

        # Clean up whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        return text.strip()
    except Exception as e:
        return f"[Could not extract webpage content: {e}]"


def identify_content_type(url):
    """Identify the type of content from a URL."""
    url_lower = url.lower()
    parsed = urlparse(url)

    # Video platforms
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'youtube'
    if 'vimeo.com' in url_lower:
        return 'vimeo'
    if 'panopto' in url_lower:
        return 'panopto'

    # Documents
    if url_lower.endswith('.pdf'):
        return 'pdf'
    if url_lower.endswith(('.doc', '.docx')):
        return 'word'
    if url_lower.endswith(('.ppt', '.pptx')):
        return 'powerpoint'

    # Default to webpage
    return 'webpage'


def process_module_item(item, page=None, download_dir=None):
    """Process a module item and extract its content."""
    item_type = item.get('type', '').lower()
    content = {
        'title': item.get('title', 'Untitled'),
        'type': item_type,
        'url': item.get('url') or item.get('html_url') or item.get('external_url'),
        'content': None,
        'extracted': False,
    }

    if item_type == 'page':
        # Canvas page - content should be fetched separately
        content['content'] = item.get('body', '[Page content not loaded]')
        content['extracted'] = bool(item.get('body'))

    elif item_type == 'externalurl':
        external_url = item.get('external_url', '')
        content['url'] = external_url
        content_type = identify_content_type(external_url)

        if content_type == 'youtube':
            video_id = extract_youtube_id(external_url)
            if video_id:
                content['content'] = get_youtube_transcript(video_id)
                content['extracted'] = not content['content'].startswith('[Could not')
                content['video_id'] = video_id
        elif content_type == 'panopto':
            video_id, panopto_host = extract_panopto_id(external_url)
            if video_id and panopto_host:
                content['content'] = get_panopto_transcript(video_id, panopto_host)
                content['extracted'] = not content['content'].startswith('[Panopto video')
                content['video_id'] = video_id
            else:
                content['content'] = f'[Panopto video: {external_url}]'
        elif content_type == 'pdf':
            # Download and extract external PDF
            try:
                import requests
                response = requests.get(external_url, timeout=30)
                response.raise_for_status()
                pdf_bytes = response.content
                content['content'] = extract_pdf_text(pdf_bytes)
                content['extracted'] = not content['content'].startswith('[Could not')

                # Save locally if download_dir provided
                if download_dir:
                    Path(download_dir).mkdir(parents=True, exist_ok=True)
                    # Extract filename from URL or use title
                    pdf_filename = external_url.split('/')[-1].split('?')[0]
                    if not pdf_filename.endswith('.pdf'):
                        pdf_filename = f"{item.get('title', 'document')}.pdf"
                    pdf_path = download_dir / pdf_filename
                    pdf_path.write_bytes(pdf_bytes)
                    content['local_path'] = str(pdf_path)
            except Exception as e:
                content['content'] = f'[Could not download PDF: {e}]'
        else:
            content['content'] = extract_webpage_content(external_url, page)
            content['extracted'] = not content['content'].startswith('[Could not')

    elif item_type == 'file':
        file_url = item.get('url', '')
        filename = item.get('filename', '') or item.get('title', 'unknown')
        download_url = item.get('download_url')  # May be pre-fetched in headless mode

        if download_dir:
            # Ensure download directory exists
            Path(download_dir).mkdir(parents=True, exist_ok=True)
            try:
                # Get the download URL if not already fetched
                if not download_url and file_url and page:
                    # Check if page is Playwright page or HeadlessCanvasAPI
                    if hasattr(page, 'request'):
                        # Playwright page
                        file_response = page.request.get(file_url)
                        if file_response.ok:
                            file_data = file_response.json()
                            download_url = file_data.get('url')
                            filename = file_data.get('filename', filename)
                    elif hasattr(page, 'get_raw'):
                        # HeadlessCanvasAPI
                        from .canvas_browser import get_canvas_url
                        canvas_url = get_canvas_url()
                        file_data = page.get(file_url.replace(canvas_url, ''))
                        download_url = file_data.get('url')
                        filename = file_data.get('filename', filename)

                if download_url:
                    # Download the file using authenticated session if available
                    if hasattr(page, 'get_raw'):
                        # HeadlessCanvasAPI - use its authenticated session
                        dl_response = page.get_raw(download_url)
                        file_bytes = dl_response.content
                    elif hasattr(page, 'request'):
                        # Playwright page - use its request context
                        dl_response = page.request.get(download_url)
                        if not dl_response.ok:
                            raise Exception(f"Download failed: {dl_response.status}")
                        file_bytes = dl_response.body()
                    else:
                        # Fallback to unauthenticated request
                        import requests
                        dl_response = requests.get(download_url, timeout=60)
                        dl_response.raise_for_status()
                        file_bytes = dl_response.content

                    # Save file locally
                    file_path = download_dir / filename
                    file_path.write_bytes(file_bytes)
                    content['local_path'] = str(file_path)

                    # Process based on file type
                    if filename.lower().endswith('.pdf'):
                        content['content'] = extract_pdf_text(file_bytes)
                        content['extracted'] = not content['content'].startswith('[Could not')
                    elif filename.lower().endswith('.zip'):
                        # Extract zip and process contents
                        zip_extract_dir = download_dir / filename.replace('.zip', '')
                        content['content'] = extract_zip_contents(file_bytes, zip_extract_dir)
                        content['extracted'] = not content['content'].startswith('[Could not')
                        content['extracted_to'] = str(zip_extract_dir)
                    else:
                        content['content'] = f'[File saved: {filename}]'
                        content['extracted'] = True
                else:
                    content['content'] = f'[File: {filename} - could not get download URL]'
            except Exception as e:
                content['content'] = f'[Could not download file: {e}]'
        else:
            content['content'] = f'[File: {filename} - sync with browser to download]'

    elif item_type == 'externaltool':
        # External tools (like Panopto, Kaltura, etc.)
        # Try to extract URL from external tool attributes
        tool_url = item.get('external_url') or item.get('url') or ''
        title = item.get('title', 'External Tool')

        if 'panopto' in tool_url.lower():
            video_id, panopto_host = extract_panopto_id(tool_url)
            if video_id and panopto_host:
                content['content'] = get_panopto_transcript(video_id, panopto_host)
                content['extracted'] = not content['content'].startswith('[Panopto video')
                content['video_id'] = video_id
                content['url'] = tool_url
            else:
                content['content'] = f'[Panopto video: {title}]\nURL: {tool_url}\n[Open in Canvas to view]'
        elif 'kaltura' in tool_url.lower():
            content['content'] = f'[Kaltura video: {title}]\n[Video transcripts not supported - open in Canvas to view]'
        else:
            content['content'] = f'[External tool: {title}]\n[May require manual access in Canvas]'
            if tool_url:
                content['url'] = tool_url

    return content


def save_module_content(module_data, course_dir):
    """Save module content to files."""
    modules_dir = course_dir / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize module name for filename
    module_name = re.sub(r'[<>:"/\\|?*]', '', module_data.get('name', 'Unknown'))
    module_name = re.sub(r'\s+', '_', module_name)[:50]

    module_dir = modules_dir / module_name
    module_dir.mkdir(parents=True, exist_ok=True)

    # Save module metadata
    metadata = {
        'id': module_data.get('id'),
        'name': module_data.get('name'),
        'position': module_data.get('position'),
        'items_count': len(module_data.get('items', [])),
    }

    with open(module_dir / "module.json", "w") as f:
        json.dump(metadata, f, indent=2)

    # Save content as markdown
    md_content = [f"# {module_data.get('name', 'Module')}\n"]

    items = module_data.get('items', [])
    for item in items:
        title = item.get('title', 'Untitled')
        item_type = item.get('type', 'unknown')

        md_content.append(f"\n## {title}\n")
        md_content.append(f"*Type: {item_type}*\n")

        if item.get('content'):
            md_content.append(f"\n{item['content']}\n")

        if item.get('url'):
            md_content.append(f"\nSource: {item['url']}\n")

        md_content.append("\n---\n")

    with open(module_dir / "content.md", "w") as f:
        f.write('\n'.join(md_content))

    return module_dir


def fetch_and_process_modules(page, course_id, course_dir):
    """Fetch all modules for a course and process their content."""
    from .canvas_browser import get_canvas_url
    canvas_url = get_canvas_url()

    print(f"  Fetching modules...")

    # Fetch modules with items
    response = page.request.get(
        f"{canvas_url}/api/v1/courses/{course_id}/modules?include[]=items&per_page=50"
    )

    if not response.ok:
        print(f"  ✗ Could not fetch modules: {response.status}")
        return []

    modules = response.json()
    processed_modules = []

    files_dir = course_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    for module in modules:
        module_name = module.get('name', 'Unknown Module')
        items = module.get('items', [])

        print(f"  Processing: {module_name} ({len(items)} items)")

        processed_items = []
        for item in items:
            # For pages, we need to fetch the full content
            if item.get('type') == 'Page':
                page_url = item.get('url')
                if page_url:
                    try:
                        page_response = page.request.get(page_url)
                        if page_response.ok:
                            page_data = page_response.json()
                            item['body'] = page_data.get('body', '')
                    except:
                        pass

            processed = process_module_item(item, page, files_dir)
            processed_items.append(processed)

        module['items'] = processed_items

        # Save module content
        module_dir = save_module_content(module, course_dir)

        # Count extracted items
        extracted_count = sum(1 for i in processed_items if i.get('extracted'))
        print(f"    ✓ Saved ({extracted_count}/{len(processed_items)} items extracted)")

        processed_modules.append({
            'name': module_name,
            'path': str(module_dir),
            'items_count': len(processed_items),
            'extracted_count': extracted_count,
        })

    return processed_modules
