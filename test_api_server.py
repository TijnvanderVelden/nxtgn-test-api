"""
Test API Server voor HALO MCP integratie proof-of-concept.

Deze server simuleert NxtGn Ticketing API endpoints met mock data om te
testen of een HALO agent via tools succesvol API calls kan maken.

Endpoints:
  GET  /health                    - Health check (no auth)
  GET  /events                    - List all events
  GET  /events/{id}               - Get specific event details
  GET  /events/{id}/stats         - Get scan statistics for event
  POST /entrance-plans            - Create entrance plan

Authentication:
  Bearer token via Authorization header
  Token moet matchen met TEST_API_INTERNAL_KEY in .env

Run:
  python test_api_server.py

Config (.env):
  TEST_API_PORT=8082
  TEST_API_INTERNAL_KEY=test-key-12345
"""

import json
import os
import random
import string
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Cloud hosts (Render, Railway, etc.) inject the port via the PORT env var.
# Fall back to TEST_API_PORT for local runs, then 8082 as a last resort.
PORT = int(os.getenv('PORT') or os.getenv('TEST_API_PORT') or '8082')
INTERNAL_KEY = os.getenv('TEST_API_INTERNAL_KEY', 'test-key-12345')

# --- NxtGn Partner API (live mode) -----------------------------------------
# When these env vars are set, the server fetches real data from the NxtGn
# Partner API instead of returning mock data. Otherwise it falls back to mock.
PARTNER_BASE = (os.getenv('PARTNER_API_BASE_URL') or '').rstrip('/')
PARTNER_SIGNIN = os.getenv('PARTNER_API_SIGNIN_URL') or (f'{PARTNER_BASE}/auth/signin' if PARTNER_BASE else '')
PARTNER_EMAIL = os.getenv('PARTNER_API_EMAIL')
PARTNER_PASSWORD = os.getenv('PARTNER_API_PASSWORD')
PARTNER_TTL = int(os.getenv('PARTNER_API_TTL', '3000'))  # token cache seconds (~50 min)
PARTNER_MAX_EVENTS = int(os.getenv('PARTNER_API_MAX_EVENTS', '25'))  # cap list size for readability
LIVE_MODE = bool(PARTNER_BASE and PARTNER_SIGNIN and PARTNER_EMAIL and PARTNER_PASSWORD)

# In-memory token cache: signin once, reuse until it (nearly) expires.
_token_cache = {'token': None, 'expires_at': 0.0}


def get_partner_token():
    """Return a cached Partner API bearer token, signing in again when expired."""
    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at']:
        return _token_cache['token']
    resp = requests.post(PARTNER_SIGNIN,
                         json={'email': PARTNER_EMAIL, 'password': PARTNER_PASSWORD},
                         headers={'Accept': 'application/json'}, timeout=15)
    resp.raise_for_status()
    token = resp.json().get('access_token')
    if not token:
        raise RuntimeError('No access_token in signin response')
    _token_cache['token'] = token
    _token_cache['expires_at'] = now + PARTNER_TTL
    print('  [LIVE] Partner API token refreshed', flush=True)
    return token


def partner_get(path):
    """GET a resource from the Partner API using the cached bearer token."""
    token = get_partner_token()
    url = f'{PARTNER_BASE}/{path.lstrip("/")}'
    resp = requests.get(url, headers={'Authorization': f'Bearer {token}',
                                      'Accept': 'application/json'}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def trim_event(ev):
    """Reduce a raw Partner API event to the fields a dashboard needs."""
    if not isinstance(ev, dict):
        return ev
    venue = ev.get('venue')
    venue_name = venue.get('name') if isinstance(venue, dict) else venue
    return {
        'id': ev.get('uuid'),
        'name': ev.get('name'),
        'start_at': ev.get('start_at'),
        'end_at': ev.get('end_at'),
        'venue': venue_name,
        'is_visible': ev.get('is_visible'),
    }

# Mock data storage (in-memory)
MOCK_EVENTS = {
    "1": {
        "id": "1",
        "name": "Summer Festival 2026",
        "date": "2026-07-15",
        "location": "Amsterdam Arena",
        "capacity": 50000,
        "status": "active"
    },
    "2": {
        "id": "2",
        "name": "Winter Gala",
        "date": "2026-12-20",
        "location": "Rotterdam Ahoy",
        "capacity": 15000,
        "status": "active"
    }
}

MOCK_STATISTICS = {
    "1": {
        "event_id": "1",
        "event_name": "Summer Festival 2026",
        "total_scans": 3847,
        "unique_visitors": 3421,
        "check_ins": 3847,
        "check_outs": 426,
        "currently_inside": 3421,
        "last_scan": "2026-07-15T20:45:32Z",
        "peak_hour": "20:00-21:00",
        "capacity_percentage": 68.42
    },
    "2": {
        "event_id": "2",
        "event_name": "Winter Gala",
        "total_scans": 1247,
        "unique_visitors": 1189,
        "check_ins": 1247,
        "check_outs": 58,
        "currently_inside": 1189,
        "last_scan": "2026-12-20T19:22:15Z",
        "peak_hour": "19:00-20:00",
        "capacity_percentage": 79.27
    }
}

# In-memory storage for created entrance plans
ENTRANCE_PLANS = []


def generate_random_string(length=8):
    """Generate random alphanumeric string for credentials."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


class TestAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for test API server."""

    def log_message(self, fmt, *args):
        """Override to customize log format."""
        print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {fmt % args}')

    def _send_json(self, status, payload):
        """Send JSON response with CORS headers."""
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        """Read and parse JSON request body."""
        length = int(self.headers.get('Content-Length', '0'))
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length)
            decoded = raw.decode('utf-8')
            print(f'  [DEBUG] Content-Type={self.headers.get("Content-Type")!r} '
                  f'raw body={decoded!r}', flush=True)
            parsed = json.loads(decoded)
            # Tolerate double-encoded JSON (a JSON string containing JSON)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return parsed
        except json.JSONDecodeError as e:
            raise ValueError(f'Invalid JSON payload: {e}')

    def _auth_check(self):
        """Check Bearer token authentication."""
        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return False
        token = auth.split(' ', 1)[1].strip()
        return token == INTERNAL_KEY

    def _send_error(self, status, message):
        """Send error response."""
        self._send_json(status, {
            'error': message,
            'status': status,
            'timestamp': datetime.now().isoformat()
        })

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # Health check (no auth required)
        if path == '/health':
            self._send_json(200, {
                'status': 'healthy',
                'server': 'Test API Server',
                'version': '1.0.0',
                'timestamp': datetime.now().isoformat()
            })
            return

        # All other endpoints require authentication
        if not self._auth_check():
            self._send_error(401, 'Unauthorized: Invalid or missing Bearer token')
            return

        try:
            # GET /events - List all events
            if path == '/events':
                if LIVE_MODE:
                    raw = partner_get('/events')
                    items = raw if isinstance(raw, list) else raw.get('events', [])
                    events_list = [trim_event(e) for e in items[:PARTNER_MAX_EVENTS]]
                    self._send_json(200, {
                        'events': events_list,
                        'count': len(events_list),
                        'total_available': len(items),
                        'source': 'partner_api_live',
                        'timestamp': datetime.now().isoformat()
                    })
                    return
                events_list = list(MOCK_EVENTS.values())
                self._send_json(200, {
                    'events': events_list,
                    'count': len(events_list),
                    'source': 'mock',
                    'timestamp': datetime.now().isoformat()
                })
                return

            # GET /events/{id} - Get specific event
            if path.startswith('/events/') and not path.endswith('/stats'):
                event_id = path.split('/')[-1]
                if LIVE_MODE:
                    raw = partner_get('/events')
                    items = raw if isinstance(raw, list) else raw.get('events', [])
                    match = next((e for e in items if isinstance(e, dict)
                                  and e.get('uuid') == event_id), None)
                    if match:
                        self._send_json(200, {
                            'event': match,
                            'source': 'partner_api_live',
                            'timestamp': datetime.now().isoformat()
                        })
                    else:
                        self._send_error(404, f'Event not found: {event_id}')
                    return
                event = MOCK_EVENTS.get(event_id)
                if event:
                    self._send_json(200, {
                        'event': event,
                        'timestamp': datetime.now().isoformat()
                    })
                else:
                    self._send_error(404, f'Event not found: {event_id}')
                return

            # GET /events/{id}/stats - Get scan statistics
            if path.startswith('/events/') and path.endswith('/stats'):
                event_id = path.split('/')[-2]
                if LIVE_MODE:
                    self._send_json(200, {
                        'message': 'Scan statistics are not available via the NxtGn Partner API in this POC (only event data is live).',
                        'source': 'partner_api_live',
                        'timestamp': datetime.now().isoformat()
                    })
                    return
                if event_id not in MOCK_EVENTS:
                    self._send_error(404, f'Event not found: {event_id}')
                    return

                stats = MOCK_STATISTICS.get(event_id, {})
                self._send_json(200, {
                    'statistics': stats,
                    'timestamp': datetime.now().isoformat()
                })
                return

            # GET /entrance-plans - List created entrance plans
            if path == '/entrance-plans':
                self._send_json(200, {
                    'entrance_plans': ENTRANCE_PLANS,
                    'count': len(ENTRANCE_PLANS),
                    'timestamp': datetime.now().isoformat()
                })
                return

            # Unknown endpoint
            self._send_error(404, f'Endpoint not found: {path}')

        except Exception as e:
            print(f'Error handling GET {path}: {e}')
            self._send_error(500, f'Internal server error: {str(e)}')

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # All POST endpoints require authentication
        if not self._auth_check():
            self._send_error(401, 'Unauthorized: Invalid or missing Bearer token')
            return

        try:
            # POST /entrance-plans - Create entrance plan
            if path == '/entrance-plans':
                if LIVE_MODE:
                    self._send_json(200, {
                        'success': False,
                        'message': 'Creating entrance plans is not available via the NxtGn Partner API in this POC (event data is read-only/live).',
                        'source': 'partner_api_live',
                        'timestamp': datetime.now().isoformat()
                    })
                    return

                body = self._read_json()

                if not isinstance(body, dict):
                    self._send_error(400, f'Body must be a JSON object, got {type(body).__name__}')
                    return

                # Validate required fields
                event_id = body.get('event_id')
                plan_name = body.get('name')

                if not event_id or not plan_name:
                    self._send_error(400, 'Missing required fields: event_id, name')
                    return

                # Validate event exists
                if event_id not in MOCK_EVENTS:
                    self._send_error(404, f'Event not found: {event_id}')
                    return

                # Generate credentials
                username = f'scan_{event_id}_{generate_random_string(4)}'
                password = generate_random_string(12)
                plan_id = f'ep_{len(ENTRANCE_PLANS) + 1}'

                # Create entrance plan
                entrance_plan = {
                    'id': plan_id,
                    'event_id': event_id,
                    'event_name': MOCK_EVENTS[event_id]['name'],
                    'name': plan_name,
                    'username': username,
                    'password': password,
                    'qr_code_url': f'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={username}:{password}',
                    'status': 'active',
                    'created_at': datetime.now().isoformat()
                }

                # Store in memory
                ENTRANCE_PLANS.append(entrance_plan)

                self._send_json(201, {
                    'success': True,
                    'message': f'Entrance plan "{plan_name}" created successfully',
                    'entrance_plan': entrance_plan,
                    'timestamp': datetime.now().isoformat()
                })
                return

            # Unknown endpoint
            self._send_error(404, f'Endpoint not found: {path}')

        except ValueError as e:
            self._send_error(400, str(e))
        except Exception as e:
            print(f'Error handling POST {path}: {e}')
            self._send_error(500, f'Internal server error: {str(e)}')


def run_server():
    """Start the test API server."""
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, TestAPIHandler)

    print('\n' + '='*60)
    print('>>> Test API Server gestart')
    print('='*60)
    print(f'Port: {PORT}')
    print(f'Authentication: Bearer {INTERNAL_KEY}')
    if LIVE_MODE:
        print(f'Data mode: LIVE  -> NxtGn Partner API ({PARTNER_BASE})')
    else:
        print('Data mode: MOCK  (set PARTNER_API_* env vars for live data)')
    print(f'\nEndpoints:')
    print(f'  GET  http://localhost:{PORT}/health')
    print(f'  GET  http://localhost:{PORT}/events')
    print(f'  GET  http://localhost:{PORT}/events/{{id}}')
    print(f'  GET  http://localhost:{PORT}/events/{{id}}/stats')
    print(f'  POST http://localhost:{PORT}/entrance-plans')
    print(f'\nTest met curl:')
    print(f'  curl http://localhost:{PORT}/health')
    print(f'  curl -H "Authorization: Bearer {INTERNAL_KEY}" http://localhost:{PORT}/events')
    print('\nDruk Ctrl+C om te stoppen')
    print('='*60 + '\n')

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n\n>>> Server gestopt')
        httpd.server_close()


if __name__ == '__main__':
    run_server()
