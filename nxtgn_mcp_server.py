"""
NxtGn Ticketing — MCP server (leer-prototype).

Dit is de "echte MCP-server"-variant van onze proxy: dezelfde Partner API-logica
(signin/token-cache, paginatie), maar nu verpakt als ZELFBESCHRIJVENDE MCP-tools.
Een MCP-client (Claude Desktop/Code, of ons testscript) vraagt "wat kun je?" en
krijgt automatisch de tools met hun parameter-schema's terug — geen endpoint-kaart
in een agent nodig.

Run (HTTP-transport):
  python nxtgn_mcp_server.py
  -> MCP endpoint op http://127.0.0.1:8090/mcp

Config (.env): PARTNER_API_BASE_URL, PARTNER_API_SIGNIN_URL, PARTNER_API_EMAIL,
PARTNER_API_PASSWORD  (zelfde als de proxy).
"""

import os
import time

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

PARTNER_BASE = (os.getenv('PARTNER_API_BASE_URL') or '').rstrip('/')
PARTNER_SIGNIN = os.getenv('PARTNER_API_SIGNIN_URL') or (f'{PARTNER_BASE}/auth/signin' if PARTNER_BASE else '')
PARTNER_EMAIL = os.getenv('PARTNER_API_EMAIL')
PARTNER_PASSWORD = os.getenv('PARTNER_API_PASSWORD')
PARTNER_TTL = int(os.getenv('PARTNER_API_TTL', '3000'))

_token_cache = {'token': None, 'expires_at': 0.0}
_events_cache = {'events': None, 'expires_at': 0.0}


# --- Partner API helpers (hergebruik van de proxy) -------------------------
def get_token():
    now = time.time()
    if _token_cache['token'] and now < _token_cache['expires_at']:
        return _token_cache['token']
    r = requests.post(PARTNER_SIGNIN, json={'email': PARTNER_EMAIL, 'password': PARTNER_PASSWORD},
                      headers={'Accept': 'application/json'}, timeout=15)
    r.raise_for_status()
    token = r.json().get('access_token')
    if not token:
        raise RuntimeError('No access_token in signin response')
    _token_cache.update(token=token, expires_at=now + PARTNER_TTL)
    return token


def api(method, path, body=None):
    token = get_token()
    url = f'{PARTNER_BASE}/{path.lstrip("/")}'
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json',
               'Content-Type': 'application/json'}
    if '/reservations' in path:
        headers['X-TF-DISTRIBUTION-METHOD'] = 'EMAIL'
    if method == 'POST':
        r = requests.post(url, headers=headers, json=body, timeout=30)
    else:
        r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return r.text


def all_events():
    now = time.time()
    if _events_cache['events'] is not None and now < _events_cache['expires_at']:
        return _events_cache['events']
    token = get_token()
    out, skip, total = [], 0, None
    for _ in range(200):
        r = requests.get(f'{PARTNER_BASE}/events',
                         headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json',
                                  'X-TF-PAGINATION-SKIP': str(skip)}, timeout=30)
        r.raise_for_status()
        page = r.json()
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if total is None:
            try:
                total = int(r.headers.get('x-tf-pagination-total') or 0)
            except (TypeError, ValueError):
                total = 0
        skip += len(page)
        if total and skip >= total:
            break
    _events_cache.update(events=out, expires_at=now + 60)
    return out


def _name(ev):
    n = ev.get('name')
    if isinstance(n, dict):
        return n.get('en') or n.get('nl') or next(iter(n.values()), None)
    return n


def slim_event(ev):
    venue = ev.get('venue')
    return {
        'event_uuid': ev.get('uuid') or ev.get('id'),
        'name': _name(ev),
        'start_at': ev.get('start_at'),
        'end_at': ev.get('end_at'),
        'venue': venue.get('name') if isinstance(venue, dict) else venue,
    }


# --- MCP server + tools ----------------------------------------------------
mcp = FastMCP('NxtGn Ticketing', host='127.0.0.1', port=8090)


@mcp.tool()
def search_events(query: str) -> list[dict]:
    """Search NxtGn events by (partial) name. Returns matching events with their
    event_uuid, name, dates and venue. Use this first to resolve an event the
    user named to its event_uuid before calling other tools."""
    q = (query or '').strip().lower()
    matches = [slim_event(e) for e in all_events() if q in (str(_name(e) or '')).lower()]
    return matches


@mcp.tool()
def list_events(limit: int = 50) -> list[dict]:
    """List NxtGn events (up to `limit`, default 50). Returns event_uuid, name,
    dates and venue for each."""
    return [slim_event(e) for e in all_events()[:limit]]


@mcp.tool()
def get_event(event_uuid: str) -> dict:
    """Get the full details of one event by its event_uuid."""
    match = next((e for e in all_events() if (e.get('uuid') or e.get('id')) == event_uuid), None)
    return match or {'error': f'Event not found: {event_uuid}'}


@mcp.tool()
def list_products(event_uuid: str) -> list[dict]:
    """List the ticket types / products for an event. Returns each product's
    product_uuid, name, price, stock and capacity. The product_uuid is needed to
    create a reservation."""
    data = api('GET', f'/events/{event_uuid}/products')
    items = data if isinstance(data, list) else data.get('data', data) if isinstance(data, dict) else []
    out = []
    for p in (items or []):
        out.append({
            'product_uuid': p.get('uuid'),
            'name': _name(p),
            'price': p.get('price'),
            'stock': p.get('stock'),
            'capacity': p.get('capacity'),
            'status': p.get('ticket_status_type_id'),
        })
    return out


@mcp.tool()
def list_orders(event_uuid: str, status: str = '') -> dict:
    """List orders for an event. Optionally filter by status (e.g. 'COMPLETED')."""
    path = f'/events/{event_uuid}/orders'
    if status:
        path += f'?status={status}'
    return {'orders': api('GET', path)}


@mcp.tool()
def get_order(event_uuid: str, order_id: str) -> dict:
    """Get the details of one order (by order_id, e.g. CMxxxxxxxx) for an event."""
    return api('GET', f'/events/{event_uuid}/orders/{order_id}')


@mcp.tool()
def list_barcodes(event_uuid: str) -> dict:
    """List the barcodes (issued tickets) for an event."""
    return {'barcodes': api('GET', f'/events/{event_uuid}/barcodes')}


@mcp.tool()
def create_reservation(event_uuid: str, ticket_type_uuid: str, amount: int,
                       first_name: str, last_name: str, email: str, mobile: str = '+31600000000') -> dict:
    """Create a ticket reservation (a real sandbox hold). Returns the order_id and
    barcodes (status PENDING). Follow up with complete_reservation to finalise.
    Needs the event_uuid and the product/ticket_type_uuid (from list_products)."""
    body = {
        'ticket_types': [{'uuid': ticket_type_uuid, 'amount': amount}],
        'customer_data': {'first_name': first_name, 'last_name': last_name,
                          'email': email, 'mobile': mobile},
    }
    res = api('POST', f'/events/{event_uuid}/reservations/create', body)
    oid = res.get('order_id') if isinstance(res, dict) else None
    return {'order_id': oid, 'total_balance_incl_vat': res.get('total_balance_incl_vat') if isinstance(res, dict) else None,
            'result': res}


@mcp.tool()
def complete_reservation(event_uuid: str, order_id: str) -> dict:
    """Finalise a reservation created with create_reservation. Use the order_id
    (CMxxxxxxxx), not the order_uuid. No payment method needed. Returns the
    download_url and the barcodes (status COMPLETED)."""
    res = api('POST', f'/events/{event_uuid}/reservations/{order_id}/complete', None)
    return {'download_url': res.get('download_url') if isinstance(res, dict) else None, 'result': res}


if __name__ == '__main__':
    print('NxtGn MCP server -> http://127.0.0.1:8090/mcp  (transport: streamable-http)', flush=True)
    mcp.run(transport='streamable-http')
