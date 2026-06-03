"""
Verkennings-script voor de NxtGn Partner API (read-only).

Logt in met de credentials uit .env, doet GET /events en toont
de STRUCTUUR van het antwoord. Print NOOIT je wachtwoord of token.

Run vanuit de projectmap:
  python partner_api_probe.py
"""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = (os.getenv('PARTNER_API_BASE_URL') or '').rstrip('/')
# Volledig signin-adres expliciet; valt terug op BASE + /auth/signin als niet gezet.
SIGNIN_URL = os.getenv('PARTNER_API_SIGNIN_URL') or (f'{BASE}/auth/signin' if BASE else '')
EMAIL = os.getenv('PARTNER_API_EMAIL')
PASSWORD = os.getenv('PARTNER_API_PASSWORD')


def mask(value):
    """Toon alleen begin/eind zodat we niets gevoeligs lekken."""
    if not value:
        return '(leeg)'
    return f'{value[:2]}***{value[-1:]} (len {len(value)})'


def main():
    print('=== Config ===')
    print(f'BASE_URL   : {BASE or "(niet gezet!)"}')
    print(f'SIGNIN_URL : {SIGNIN_URL or "(niet gezet!)"}')
    print(f'EMAIL      : {mask(EMAIL)}')
    print(f'PASSWORD   : {"gezet" if PASSWORD else "(niet gezet!)"}')

    if not (BASE and SIGNIN_URL and EMAIL and PASSWORD):
        print('\n>> Vul eerst PARTNER_API_BASE_URL, PARTNER_API_EMAIL en '
              'PARTNER_API_PASSWORD in .env in (PARTNER_API_SIGNIN_URL optioneel).')
        return

    # 1) Inloggen -> access_token
    print('\n=== 1) Signin ===')
    signin_url = SIGNIN_URL
    try:
        r = requests.post(signin_url, json={'email': EMAIL, 'password': PASSWORD},
                          headers={'Accept': 'application/json'}, timeout=15)
    except Exception as e:
        print(f'Signin request faalde: {e}')
        return

    print(f'POST {signin_url} -> HTTP {r.status_code}')
    if r.status_code >= 400:
        print(f'Body (eerste 300 tekens): {r.text[:300]}')
        return

    try:
        data = r.json()
    except Exception:
        print(f'Geen JSON terug. Body: {r.text[:300]}')
        return

    token = data.get('access_token')
    if not token:
        print(f'Geen access_token gevonden. Beschikbare velden: {list(data.keys())}')
        return
    print(f'access_token ontvangen: {mask(token)}')

    # 2) GET /events
    print('\n=== 2) GET /events ===')
    events_url = f'{BASE}/events'
    try:
        r2 = requests.get(events_url, headers={'Authorization': f'Bearer {token}',
                                               'Accept': 'application/json'}, timeout=20)
    except Exception as e:
        print(f'Events request faalde: {e}')
        return

    print(f'GET {events_url} -> HTTP {r2.status_code}')
    if r2.status_code >= 400:
        print(f'Body (eerste 400 tekens): {r2.text[:400]}')
        return

    body = r2.json()
    print(f'\nType van response: {type(body).__name__}')

    # Structuur tonen
    if isinstance(body, dict):
        print(f'Top-level velden: {list(body.keys())}')
        # zoek een lijst met events binnenin
        for k, v in body.items():
            if isinstance(v, list) and v:
                print(f'\n"{k}" is een lijst met {len(v)} items. '
                      f'Velden van eerste item: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0]).__name__}')
                break
    elif isinstance(body, list):
        print(f'Lijst met {len(body)} items. '
              f'Velden eerste item: {list(body[0].keys()) if body and isinstance(body[0], dict) else "?"}')

    print('\n=== Voorbeeld (eerste ~900 tekens, sandbox-data) ===')
    print(json.dumps(body, indent=2, ensure_ascii=False)[:900])


if __name__ == '__main__':
    main()
