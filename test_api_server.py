"""
Test API Server voor HALO MCP integratie proof-of-concept.

Twee modi:

1. MOCK (geen Partner-credentials gezet): geeft verzonnen events/statistieken
   terug. Handig om de HALO-keten te testen zonder echte API.

2. LIVE (PARTNER_API_* env vars gezet): werkt als een geauthenticeerde proxy
   naar de NxtGn General Admission Partner API. De server logt zelf in
   (token caching/refresh) en hangt automatisch de Bearer-token + juiste
   headers aan elk pad dat de HALO-tool meegeeft. Daardoor zijn ALLE Partner
   API-endpoints bruikbaar zonder ze stuk voor stuk in te bouwen.

   Voorbeeldpaden (de agent kettingt de variabelen zelf):
     GET  /events
     GET  /events/{event_uuid}
     GET  /events/{event_uuid}/products
     GET  /events/{event_uuid}/orders?status=COMPLETED
     GET  /events/{event_uuid}/orders/{order_id}
     POST /events/{event_uuid}/reservations/generate   (body: ticket_types + customer_data)
     POST /events/{event_uuid}/reservations/create
     POST /events/{event_uuid}/reservations/{order_id}/complete

Authentication (HALO -> deze server):
  Bearer token via Authorization header, moet matchen met TEST_API_INTERNAL_KEY.

Run:
  python test_api_server.py

Config (.env / env vars):
  PORT / TEST_API_PORT          - poort (default 8082; cloud hosts zetten PORT)
  TEST_API_INTERNAL_KEY         - Bearer-token tussen HALO en deze server
  PARTNER_API_BASE_URL          - bv. https://api.ticketing.cm.com/partnerapi/v1.0
  PARTNER_API_SIGNIN_URL        - bv. <base>/auth/signin
  PARTNER_API_EMAIL             - Partner API signin e-mail
  PARTNER_API_PASSWORD          - Partner API signin wachtwoord
  PARTNER_API_TTL               - token-cache in seconden (default 3000)
  PARTNER_API_MAX_EVENTS        - max events in /events lijst (default 50)
"""

import json
import os
import random
import string
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

PORT = int(os.getenv('PORT') or os.getenv('TEST_API_PORT') or '8082')
INTERNAL_KEY = os.getenv('TEST_API_INTERNAL_KEY', 'test-key-12345')

# --- NxtGn Partner API (live mode) -----------------------------------------
PARTNER_BASE = (os.getenv('PARTNER_API_BASE_URL') or '').rstrip('/')
PARTNER_SIGNIN = os.getenv('PARTNER_API_SIGNIN_URL') or (f'{PARTNER_BASE}/auth/signin' if PARTNER_BASE else '')
PARTNER_EMAIL = os.getenv('PARTNER_API_EMAIL')
PARTNER_PASSWORD = os.getenv('PARTNER_API_PASSWORD')
PARTNER_TTL = int(os.getenv('PARTNER_API_TTL', '3000'))          # token cache seconds (~50 min)
PARTNER_MAX_EVENTS = int(os.getenv('PARTNER_API_MAX_EVENTS', '50'))
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


def partner_request(method, path, body=None):
    """Forward a request to the Partner API with auth attached.

    `path` is the resource path (with optional ?query) exactly as the caller
    requested it. Returns (http_status, parsed_body_or_text).
    """
    token = get_partner_token()
    url = f'{PARTNER_BASE}/{path.lstrip("/")}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    # Reservations require a distribution method header.
    if '/reservations' in path:
        headers['X-TF-DISTRIBUTION-METHOD'] = 'EMAIL'

    if method == 'POST':
        json_body = body
        if isinstance(body, str):
            json_body = json.loads(body) if body.strip() else None
        resp = requests.post(url, headers=headers, json=json_body, timeout=30)
    else:
        resp = requests.get(url, headers=headers, timeout=30)

    try:
        parsed = resp.json()
    except Exception:
        parsed = resp.text
    return resp.status_code, parsed


# Short cache of the full (paginated) events list to avoid refetching every call.
_events_cache = {'events': None, 'expires_at': 0.0}


def fetch_all_events():
    """Fetch ALL events across every page (the Partner API paginates).

    Uses the X-TF-PAGINATION-SKIP header and the x-tf-pagination-total response
    header to walk through every page, so search/listing covers all events.
    """
    now = time.time()
    if _events_cache['events'] is not None and now < _events_cache['expires_at']:
        return _events_cache['events']

    token = get_partner_token()
    url = f'{PARTNER_BASE}/events'
    all_events = []
    skip = 0
    total = None
    for _ in range(200):  # safety cap (max 200 pages)
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'X-TF-PAGINATION-SKIP': str(skip),
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        all_events.extend(page)
        if total is None:
            try:
                total = int(resp.headers.get('x-tf-pagination-total') or 0)
            except (TypeError, ValueError):
                total = 0
        skip += len(page)
        if total and skip >= total:
            break

    _events_cache['events'] = all_events
    _events_cache['expires_at'] = now + 60  # cache for 60s
    print(f'  [LIVE] fetched {len(all_events)} events (total header={total})', flush=True)
    return all_events


def trim_event(ev):
    """Reduce a raw Partner API event to the fields a dashboard needs."""
    if not isinstance(ev, dict):
        return ev
    venue = ev.get('venue')
    venue_name = venue.get('name') if isinstance(venue, dict) else venue
    name = ev.get('name')
    if isinstance(name, dict):
        name = name.get('en') or name.get('nl') or next(iter(name.values()), None)
    return {
        'id': ev.get('uuid') or ev.get('id'),
        'name': name,
        'start_at': ev.get('start_at'),
        'end_at': ev.get('end_at'),
        'venue': venue_name,
        'is_visible': ev.get('is_visible'),
    }


# --- Mock data (fallback when no Partner credentials) ----------------------
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

# In-memory storage for created entrance plans (mock mode only)
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
        """Read and parse JSON request body (tolerant of double-encoded JSON)."""
        length = int(self.headers.get('Content-Length', '0'))
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length)
            decoded = raw.decode('utf-8')
            parsed = json.loads(decoded)
            # HALO http_activity may double-encode a string body. An empty body
            # arrives as a JSON-encoded empty string ("") — treat that as no body
            # instead of trying (and failing) to json.loads("").
            if isinstance(parsed, str):
                stripped = parsed.strip()
                parsed = json.loads(stripped) if stripped else {}
            return parsed
        except json.JSONDecodeError as e:
            raise ValueError(f'Invalid JSON payload: {e}')

    def _auth_check(self):
        """Check Bearer token authentication (HALO -> this server)."""
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

    # --- live-mode proxy helpers -------------------------------------------
    def _live_get(self):
        """Proxy a GET to the Partner API.

        For the /events list we fetch the full list and (optionally) filter it
        server-side by ?search=<term> so the agent can reliably resolve the
        event the user named to its event_uuid — without ever guessing.
        """
        parsed = urlparse(self.path)
        resource_path = parsed.path

        # Special handling for the events list (all pages + search + trim).
        if resource_path == '/events':
            try:
                data = fetch_all_events()
            except Exception as e:
                self._send_json(200, {'status': 502, 'error': f'Partner API call failed: {e}',
                                      'source': 'partner_api_live', 'timestamp': datetime.now().isoformat()})
                return

            trimmed = [trim_event(e) for e in data]
            search = (parse_qs(parsed.query).get('search', [''])[0] or '').strip().lower()
            if search:
                matches = [e for e in trimmed if search in (str(e.get('name') or '')).lower()]
            else:
                matches = trimmed[:PARTNER_MAX_EVENTS]

            self._send_json(200, {
                'events': matches,
                'count': len(matches),
                'total_available': len(data),
                'search': search or None,
                'note': ('Pass ?search=<event name> to find a specific event and its id.'
                         if not search else None),
                'source': 'partner_api_live',
                'timestamp': datetime.now().isoformat()
            })
            return

        # Everything else: forward the full path (incl. query) untouched.
        # Always answer HALO with HTTP 200 and put the REAL upstream status in the
        # body, so the agent can see error details instead of HALO hard-failing on 4xx.
        try:
            status, data = partner_request('GET', self.path)
        except Exception as e:
            self._send_json(200, {'status': 502, 'error': f'Partner API call failed: {e}',
                                  'source': 'partner_api_live', 'timestamp': datetime.now().isoformat()})
            return
        self._send_json(200, {
            'status': status,
            'data': data,
            'source': 'partner_api_live',
            'timestamp': datetime.now().isoformat()
        })

    def _live_post(self):
        """Proxy a POST to the Partner API (e.g. reservations)."""
        try:
            body = self._read_json()
        except ValueError as e:
            self._send_json(200, {'status': 400, 'error': str(e),
                                  'source': 'partner_api_live', 'timestamp': datetime.now().isoformat()})
            return
        try:
            # Empty body ({}) -> send no JSON body (matches a plain complete call).
            status, data = partner_request('POST', self.path, body or None)
        except Exception as e:
            self._send_json(200, {'status': 502, 'error': f'Partner API call failed: {e}',
                                  'source': 'partner_api_live', 'timestamp': datetime.now().isoformat()})
            return
        # Always 200 to HALO with the real upstream status in the body (so the agent
        # sees error details instead of HALO hard-failing on a 4xx).
        self._send_json(200, {
            'status': status,
            'data': data,
            'source': 'partner_api_live',
            'timestamp': datetime.now().isoformat()
        })

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # Health check (no auth required)
        if path == '/health':
            self._send_json(200, {
                'status': 'healthy',
                'server': 'Test API Server',
                'version': '2.0.0',
                'mode': 'live' if LIVE_MODE else 'mock',
                'timestamp': datetime.now().isoformat()
            })
            return

        # All other endpoints require authentication
        if not self._auth_check():
            self._send_error(401, 'Unauthorized: Invalid or missing Bearer token')
            return

        # LIVE MODE: act as an authenticated proxy to the Partner API.
        if LIVE_MODE:
            self._live_get()
            return

        try:
            # GET /events - List all events (mock)
            if path == '/events':
                events_list = list(MOCK_EVENTS.values())
                self._send_json(200, {
                    'events': events_list,
                    'count': len(events_list),
                    'source': 'mock',
                    'timestamp': datetime.now().isoformat()
                })
                return

            # GET /events/{id} - Get specific event (mock)
            if path.startswith('/events/') and not path.endswith('/stats'):
                event_id = path.split('/')[-1]
                event = MOCK_EVENTS.get(event_id)
                if event:
                    self._send_json(200, {
                        'event': event,
                        'timestamp': datetime.now().isoformat()
                    })
                else:
                    self._send_error(404, f'Event not found: {event_id}')
                return

            # GET /events/{id}/stats - Get scan statistics (mock)
            if path.startswith('/events/') and path.endswith('/stats'):
                event_id = path.split('/')[-2]
                if event_id not in MOCK_EVENTS:
                    self._send_error(404, f'Event not found: {event_id}')
                    return
                stats = MOCK_STATISTICS.get(event_id, {})
                self._send_json(200, {
                    'statistics': stats,
                    'timestamp': datetime.now().isoformat()
                })
                return

            # GET /entrance-plans - List created entrance plans (mock)
            if path == '/entrance-plans':
                self._send_json(200, {
                    'entrance_plans': ENTRANCE_PLANS,
                    'count': len(ENTRANCE_PLANS),
                    'timestamp': datetime.now().isoformat()
                })
                return

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

        # LIVE MODE: proxy the POST straight to the Partner API.
        if LIVE_MODE:
            self._live_post()
            return

        try:
            # POST /entrance-plans - Create entrance plan (mock)
            if path == '/entrance-plans':
                body = self._read_json()

                if not isinstance(body, dict):
                    self._send_error(400, f'Body must be a JSON object, got {type(body).__name__}')
                    return

                event_id = body.get('event_id')
                plan_name = body.get('name')

                if not event_id or not plan_name:
                    self._send_error(400, 'Missing required fields: event_id, name')
                    return

                if event_id not in MOCK_EVENTS:
                    self._send_error(404, f'Event not found: {event_id}')
                    return

                username = f'scan_{event_id}_{generate_random_string(4)}'
                password = generate_random_string(12)
                plan_id = f'ep_{len(ENTRANCE_PLANS) + 1}'

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
                ENTRANCE_PLANS.append(entrance_plan)

                self._send_json(201, {
                    'success': True,
                    'message': f'Entrance plan "{plan_name}" created successfully',
                    'entrance_plan': entrance_plan,
                    'timestamp': datetime.now().isoformat()
                })
                return

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

    print('\n' + '=' * 60)
    print('>>> Test API Server gestart')
    print('=' * 60)
    print(f'Port: {PORT}')
    print(f'Authentication: Bearer {INTERNAL_KEY}')
    if LIVE_MODE:
        print(f'Data mode: LIVE  -> proxy to {PARTNER_BASE}')
        print('  Any path is forwarded to the Partner API with auth attached.')
    else:
        print('Data mode: MOCK  (set PARTNER_API_* env vars for live data)')
    print('\nDruk Ctrl+C om te stoppen')
    print('=' * 60 + '\n')

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n\n>>> Server gestopt')
        httpd.server_close()


if __name__ == '__main__':
    run_server()
