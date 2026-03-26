"""Thoth Hub — HTTP server with API routes and reverse-proxy routing for bot dashboards."""

import http.server
import socketserver
import os
import json
import re
import mimetypes
import urllib.parse

PORT = 1337
HUB_DIR = os.path.dirname(os.path.abspath(__file__))
BOTS_DIR = os.path.normpath(os.path.join(HUB_DIR, '..', 'bots'))
PLANS_DIR = os.path.normpath(os.path.join(HUB_DIR, '..', 'common', 'plans'))

# Prefix → (bot_dir_name, web_subdir)
# /prefix/data/* serves from bots/<bot>/data/*, everything else from bots/<bot>/web/*
BOT_ROUTES = {
    'crumb': 'baking-bot',
    'garden': 'olivia-bot',
    'haos': 'haos-bot',
    'sag': 'sag-bot',
}


def resolve_bot_route(path):
    """Resolve a URL path to a bot file path.

    Returns (file_path, None) on success or (None, error_reason) on failure.
    """
    # Strip query string
    path = urllib.parse.urlparse(path).path

    for prefix, bot_dir in BOT_ROUTES.items():
        pattern = f'/{prefix}/'
        if not path.startswith(pattern):
            continue

        remainder = path[len(pattern):]

        # /prefix/data/* → bots/<bot>/data/*
        if remainder.startswith('data/'):
            data_path = remainder[len('data/'):]
            file_path = os.path.join(BOTS_DIR, bot_dir, 'data', data_path)
        else:
            # /prefix/* → bots/<bot>/web/*
            file_path = os.path.join(BOTS_DIR, bot_dir, 'web', remainder)

        # Default to index.html
        if file_path.endswith('/') or os.path.isdir(file_path):
            file_path = os.path.join(file_path, 'index.html')

        # Prevent path traversal
        bot_base = os.path.join(BOTS_DIR, bot_dir)
        real_path = os.path.realpath(file_path)
        real_base = os.path.realpath(bot_base)
        if not real_path.startswith(real_base + os.sep) and real_path != real_base:
            return None, 'forbidden'

        if not os.path.isfile(real_path):
            return None, 'not_found'

        return real_path, None

    return None, 'no_match'

BOT_IDS = [
    'dev_bot', 'baking-bot', 'olivia-bot', 'bennie-bot',
    'haos-bot', 'qa-bot', 'sag-bot', 'google-bot', 'image-bot',
]


def read_bot_status(bot_id):
    """Read a bot's status.json, return dict or None."""
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', bot_id)
    path = os.path.join(BOTS_DIR, safe_id, 'data', 'status.json')
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read_todos():
    """Read dev_bot todos.md and return raw text."""
    path = os.path.join(BOTS_DIR, 'dev_bot', 'data', 'todos.md')
    try:
        with open(path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return None


def parse_plan_frontmatter(text):
    """Parse YAML frontmatter from a plan markdown file.

    Returns (metadata_dict, body_str). Handles missing fields with defaults.
    """
    metadata = {}
    body = text

    # Match frontmatter between --- delimiters
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', text, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        body = fm_match.group(2).strip()

        # Simple YAML-like parser for flat key-value pairs + lists
        current_key = None
        current_list = None
        for line in fm_text.split('\n'):
            # List item under current key
            list_match = re.match(r'^\s+-\s+(.+)', line)
            if list_match and current_key:
                if current_list is None:
                    current_list = []
                current_list.append(list_match.group(1).strip())
                metadata[current_key] = current_list
                continue

            # Key-value pair
            kv_match = re.match(r'^(\w[\w_]*)\s*:\s*(.*)', line)
            if kv_match:
                # Save any pending list
                current_key = kv_match.group(1)
                value = kv_match.group(2).strip()
                current_list = None
                if value:
                    # Strip quotes
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    metadata[current_key] = value
                # If no value, might be start of a list
                continue

    # Apply defaults
    metadata.setdefault('status', 'queued')
    metadata.setdefault('priority', 'medium')
    metadata.setdefault('owner', 'unknown')
    metadata.setdefault('title', metadata.get('id', 'Untitled'))
    metadata.setdefault('last_updated', '')
    metadata.setdefault('tags', [])

    return metadata, body


def read_plans():
    """Read all plan .md files from PLANS_DIR, return list of plan dicts."""
    plans = []
    if not os.path.isdir(PLANS_DIR):
        return plans

    for fname in sorted(os.listdir(PLANS_DIR)):
        if not fname.endswith('.md'):
            continue
        if fname == 'PLAN-SCHEMA.md':
            continue

        filepath = os.path.join(PLANS_DIR, fname)
        try:
            with open(filepath, 'r') as f:
                text = f.read()
        except (FileNotFoundError, PermissionError):
            continue

        metadata, body = parse_plan_frontmatter(text)

        # Ensure id from filename if not in frontmatter
        if 'id' not in metadata:
            metadata['id'] = fname.replace('.md', '')

        # Body preview: first 200 chars
        body_preview = body[:200].strip()
        if len(body) > 200:
            body_preview += '...'

        plans.append({
            'id': metadata['id'],
            'title': metadata['title'],
            'status': metadata['status'],
            'priority': metadata['priority'],
            'owner': metadata['owner'],
            'last_updated': metadata['last_updated'],
            'channel_scope': metadata.get('channel_scope'),
            'tags': metadata.get('tags', []),
            'body_preview': body_preview,
        })

    return plans


class HubHandler(http.server.SimpleHTTPRequestHandler):
    """Extends SimpleHTTPRequestHandler with API routes and bot dashboard proxying."""

    def do_GET(self):
        # API: single bot status
        match = re.match(r'^/api/bot-status/([a-zA-Z0-9_-]+)$', self.path)
        if match:
            bot_id = match.group(1)
            data = read_bot_status(bot_id)
            if data:
                self._json_response(200, data)
            else:
                self._json_response(404, {'error': 'not found', 'bot_id': bot_id})
            return

        # API: all bot statuses
        if self.path == '/api/bots':
            results = []
            for bot_id in BOT_IDS:
                status = read_bot_status(bot_id)
                if status:
                    results.append(status)
                else:
                    results.append({
                        'bot_id': bot_id,
                        'name': bot_id,
                        'state': 'unknown',
                        'last_active': None,
                        'current_task': None,
                        'open_todos': 0,
                    })
            self._json_response(200, results)
            return

        # API: todos
        if self.path == '/api/todos':
            text = read_todos()
            if text:
                self._json_response(200, {'content': text})
            else:
                self._json_response(404, {'error': 'todos not found'})
            return

        # API: plans
        if self.path == '/api/plans':
            plans = read_plans()
            self._json_response(200, plans)
            return

        # Bot dashboard routing
        file_path, error = resolve_bot_route(self.path)
        if error is None and file_path:
            self._serve_file(file_path)
            return
        if error in ('not_found', 'forbidden'):
            self._error_response(404, 'Not Found')
            return
        # error == 'no_match' → fall through to hub static serving

        # Fall through to static file serving
        super().do_GET()

    def _json_response(self, code, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path):
        """Serve a file from an absolute path with appropriate content type."""
        content_type, _ = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = 'application/octet-stream'
        try:
            with open(file_path, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (FileNotFoundError, PermissionError):
            self._error_response(404, 'Not Found')

    def _error_response(self, code, message):
        """Send a plain-text error response."""
        body = message.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Quieter logging
        pass


def main():
    os.chdir(HUB_DIR)
    with socketserver.TCPServer(("", PORT), HubHandler) as httpd:
        print(f"Hub serving on port {PORT}")
        httpd.serve_forever()


if __name__ == '__main__':
    main()
