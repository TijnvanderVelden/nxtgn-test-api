"""
Klein MCP-client testje voor de NxtGn MCP-server.

Verbindt over streamable HTTP, vraagt de tools op (laat zien dat de server
zichzelf beschrijft: namen + parameter-schema's), en draait de keten
search_events -> list_products.

Run (terwijl nxtgn_mcp_server.py draait):
  python mcp_client_test.py
"""

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = 'http://127.0.0.1:8090/mcp'


def structured(result):
    """Haal het structured resultaat uit een CallToolResult."""
    sc = getattr(result, 'structuredContent', None)
    if isinstance(sc, dict) and 'result' in sc:
        return sc['result']
    if sc is not None:
        return sc
    # fallback: parse de tekst-content
    for c in result.content:
        if getattr(c, 'text', None):
            try:
                return json.loads(c.text)
            except Exception:
                return c.text
    return None


async def main():
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print('=' * 60)
            print('1) De server beschrijft ZICHZELF — tools + schema:')
            print('=' * 60)
            tools = await session.list_tools()
            for t in tools.tools:
                params = list((t.inputSchema or {}).get('properties', {}).keys())
                print(f'  - {t.name}({", ".join(params)})')
                if t.description:
                    print(f'      {t.description.splitlines()[0]}')

            print('\n' + '=' * 60)
            print('2) search_events("Test even Tijn")')
            print('=' * 60)
            r = await session.call_tool('search_events', {'query': 'Test even Tijn'})
            events = structured(r)
            print(json.dumps(events, indent=2, ensure_ascii=False))

            if events and isinstance(events, list):
                event_uuid = events[0]['event_uuid']
                print('\n' + '=' * 60)
                print(f'3) list_products(event_uuid={event_uuid})')
                print('=' * 60)
                r2 = await session.call_tool('list_products', {'event_uuid': event_uuid})
                print(json.dumps(structured(r2), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
