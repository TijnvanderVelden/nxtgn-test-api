# Test MCP-Style API Server → HALO Integration Plan

## Context

Deze wijziging adresseert de behoefte om te testen of een HALO agent via tools API calls kan maken naar een custom server. Dit is een proof-of-concept voor een "conversational dashboard" waarbij gebruikers via chat met een HALO agent kunnen communiceren om acties uit te voeren (zoals entrance plans aanmaken, statistieken opvragen) zonder door een UI te hoeven navigeren.

**Probleem**: Het is onduidelijk of de architectuur (HALO agent → Tool → Custom API server) werkt en hoe dit geïmplementeerd moet worden.

**Doel**: Een werkende test setup maken binnen 30-35 minuten waarbij:
- Een lokale API server draait met mock data
- HALO agent via een tool deze API kan aanroepen
- Gebruiker via Web Conversations chat kan testen of het werkt

**Waarom belangrijk**: Dit valideert het architectuurconcept voordat we investeren in een volledige NxtGn MCP integratie.

---

## Implementatie Aanpak

### Architectuur

```
Web Conversations (gebruiker)
    ↓
HALO Agent (met tool)
    ↓
HTTP Tool (met context variables)
    ↓
Ngrok (public URL)
    ↓
Test API Server (lokaal Python)
    ↓
Mock data (in-memory)
```

### Deployment Strategie

**Fase 1 (dit plan)**: Lokaal testen met ngrok
- Snelst te implementeren (15 min)
- Real-time logs voor debugging
- Geen deployment complexity

**Fase 2 (toekomst)**: Permanent deployment op Glitch/Railway
- Gratis hosting beschikbaar
- Stabiele URL (geen ngrok herstart issues)

---

## Kritieke Bestanden

### 1. **test_api_server.py** (NIEUW - 400 regels)

**Locatie**: `halo-starter-kit-main/test_api_server.py`

**Wat**: Python HTTP server met mock NxtGn endpoints

**Functionaliteit**:
- `GET /health` - Health check (geen auth)
- `GET /events` - Lijst alle events (2 mock events)
- `GET /events/{id}` - Details van specifiek event
- `GET /events/{id}/stats` - Scan statistieken voor event
- `POST /entrance-plans` - Maak entrance plan aan

**Mock data structuur**:
```python
MOCK_EVENTS = {
    "1": {
        "id": "1",
        "name": "Summer Festival 2026",
        "date": "2026-07-15",
        "location": "Amsterdam Arena",
        "capacity": 50000
    },
    "2": {
        "id": "2", 
        "name": "Winter Gala",
        "date": "2026-12-20",
        "location": "Rotterdam Ahoy",
        "capacity": 15000
    }
}

MOCK_STATISTICS = {
    "1": {
        "total_scans": 3847,
        "unique_visitors": 3421,
        "check_ins": 3847,
        "check_outs": 426,
        "currently_inside": 3421
    },
    "2": {...}
}
```

**Authenticatie**: Bearer token via `Authorization` header
- Token komt uit context variable `test_api_token`
- Valideert tegen `TEST_API_INTERNAL_KEY` uit `.env`

**Hergebruik bestaande patterns**:
- Token validatie pattern van `partner_api_proxy.py`
- JSON response formatting
- CORS headers
- Error handling (401, 404, 500)

**Poort**: 8082 (om conflict met bestaande `server.py` op 8080 te vermijden)

---

### 2. **.env** (WIJZIGEN)

**Locatie**: `halo-starter-kit-main/.env`

**Toevoegen**:
```env
# Test API Server Configuration
TEST_API_PORT=8082
TEST_API_INTERNAL_KEY=test-key-12345
TEST_API_PUBLIC_URL=https://NGROK-URL-HIER.ngrok-free.app
```

**Waarom**: Scheidt configuratie van code, makkelijk te updaten na ngrok herstart

---

### 3. **HALO Context Variables** (via HALO MCP)

**Aanmaken met**:
```bash
# Via Claude Code met /halo skill
halo_create_context(
    key="test_api_url",
    value="https://abc123.ngrok-free.app",
    description="Base URL voor test API server"
)

halo_create_context(
    key="test_api_token", 
    value="test-key-12345",
    description="Bearer token voor test API authenticatie"
)
```

**Of**: Handmatig in HALO Web UI → Profile Settings → Contexts

**Waarom context variables**:
- Veilig (token niet hardcoded in tool)
- Herbruikbaar (meerdere tools kunnen zelfde credentials gebruiken)
- Makkelijk te updaten (vooral ngrok URL die bij elke restart verandert)

---

### 4. **HALO Tool: "NxtGn API Tool"**

**Type**: HTTP Activity (HALO Tool Pattern 2)

**Parameters**:
- `endpoint` (string, required) - API path (bijv. "/events")
- `method` (string, required) - HTTP method ("GET" of "POST")  
- `body` (string, optional) - JSON body voor POST requests

**HTTP Activity configuratie**:
```json
{
  "url": "{{_context.test_api_url}}{{endpoint}}",
  "method": "{{method}}",
  "headers": {
    "Authorization": "Bearer {{_context.test_api_token}}",
    "Content-Type": "application/json"
  },
  "body": "{{body}}"
}
```

**Tool Description** (belangrijk voor agent behavior):
```
Calls the NxtGn test API to fetch event data, statistics, and create entrance plans.

Use cases:
- List all events: endpoint="/events", method="GET"
- Get event details: endpoint="/events/{id}", method="GET"  
- Get scan statistics: endpoint="/events/{id}/stats", method="GET"
- Create entrance plan: endpoint="/entrance-plans", method="POST", body='{"event_id":"1","name":"Main Gate"}'

Always use this tool when the user asks about events, statistics, or wants to create entrance plans.
```

**Waarom één generieke tool** (ipv tool per endpoint):
- Agent is slim genoeg om juiste parameters te kiezen
- Toevoegen nieuwe endpoints = geen nieuwe tool nodig
- Makkelijker te onderhouden
- Flexibeler

**Aanmaken**: Via Claude Code met `/halo` skill of HALO Web UI

---

### 5. **HALO Agent: "NxtGn Dashboard Agent"**

**Behavior Prompt**:
```markdown
You are a conversational dashboard assistant for NxtGn ticketing events.

CAPABILITIES:
- View all events
- Check scan statistics for any event
- Create entrance plans for events

TOOL USAGE:

When user asks about events:
→ Use "NxtGn API Tool" with endpoint="/events", method="GET"
→ Present events in a friendly list format

When user asks for statistics:
→ Use "NxtGn API Tool" with endpoint="/events/{id}/stats", method="GET"
→ Present stats conversationally (e.g., "3,847 people scanned, 3,421 currently inside")

When user wants to create entrance plan:
→ Ask for event ID and plan name if not provided
→ Use "NxtGn API Tool" with:
   - endpoint="/entrance-plans"
   - method="POST"  
   - body='{"event_id":"X","name":"Plan Name"}'
→ Confirm successful creation

STYLE:
- Be conversational and helpful
- Always confirm before executing POST actions
- Offer next steps (e.g., "Would you like to see the statistics for this event?")
- Format data clearly (use lists, numbers, emojis where appropriate)

EXAMPLES:

User: "Show me all events"
You: [Call tool] "Here are the upcoming events:
      1. Summer Festival 2026 - July 15 at Amsterdam Arena (capacity: 50,000)
      2. Winter Gala - Dec 20 at Rotterdam Ahoy (capacity: 15,000)
      
      Would you like to see scan statistics for any of these?"

User: "What are the stats for event 1?"
You: [Call tool] "📊 Summer Festival 2026 Statistics:
      ✅ Total scans: 3,847
      👥 Unique visitors: 3,421  
      🏟️ Currently inside: 3,421
      👋 Check-outs: 426"

User: "Create an entrance plan for event 1 called Main Gate"
You: "I'll create the entrance plan 'Main Gate' for Summer Festival 2026. Is that correct?"
User: "Yes"
You: [Call tool] "✅ Successfully created entrance plan 'Main Gate' for Summer Festival 2026!"
```

**Tools toegewezen**: "NxtGn API Tool"

**Model**: gpt-4-1-agentic (aanbevolen voor tool gebruik)

**Temperature**: 0.4

---

## Implementatie Stappen

### Stap 1: Test API Server Maken (15 min)

1. **Maak `test_api_server.py`** in project root
   - Hergebruik authentication pattern van `partner_api_proxy.py`
   - Implementeer 5 endpoints met mock data
   - Bearer token validatie
   - JSON request/response handling
   - CORS headers

2. **Update `.env`**:
   ```env
   TEST_API_PORT=8082
   TEST_API_INTERNAL_KEY=test-key-12345
   ```

3. **Test lokaal**:
   ```bash
   python test_api_server.py
   # → Test API Server gestart on port 8082
   ```

4. **Curl test**:
   ```bash
   curl -H "Authorization: Bearer test-key-12345" http://localhost:8082/events
   # → Should return JSON with 2 events
   ```

---

### Stap 2: Ngrok Setup (5 min)

1. **Installeer ngrok** (als nog niet geïnstalleerd):
   ```bash
   choco install ngrok
   # Of download van ngrok.com
   ```

2. **Start ngrok**:
   ```bash
   ngrok http 8082
   ```

3. **Kopieer HTTPS URL** (bijv. `https://abc123.ngrok-free.app`)

4. **Update `.env`**:
   ```env
   TEST_API_PUBLIC_URL=https://abc123.ngrok-free.app
   ```

5. **Test via ngrok**:
   ```bash
   curl -H "Authorization: Bearer test-key-12345" https://abc123.ngrok-free.app/events
   ```

6. **Check ngrok dashboard**: http://localhost:4040 (zie real-time requests)

---

### Stap 3: HALO Context Variables (2 min)

**Via Claude Code**:
```bash
# In Claude Code, gebruik /halo skill
"Create context variables:
- test_api_url = https://abc123.ngrok-free.app
- test_api_token = test-key-12345"
```

**Of via HALO Web UI**:
1. Login → Profile Settings → Contexts
2. Add Variable:
   - Name: `test_api_url`
   - Value: `https://abc123.ngrok-free.app`
3. Add Variable:
   - Name: `test_api_token`
   - Value: `test-key-12345`

---

### Stap 4: HALO Tool Maken (5 min)

**Via Claude Code** met `/halo` skill:
```
"Create a HALO tool called 'NxtGn API Tool' with:
- Type: HTTP Activity
- Parameters: endpoint (string), method (string), body (string, optional)
- URL: {{_context.test_api_url}}{{endpoint}}
- Method: {{method}}
- Headers: Authorization: Bearer {{_context.test_api_token}}, Content-Type: application/json
- Body: {{body}}
- Description: [copy tool description from boven]"
```

**Of via HALO Web UI**:
1. Tools → Add Tool
2. Name: "NxtGn API Tool"
3. Add Start Event → Add parameters
4. Add HTTP Activity node → Configure URL, headers, body
5. Add End Event → Return response
6. Save

---

### Stap 5: HALO Agent Configureren (3 min)

**Via Claude Code** met `/halo` skill:
```
"Create a HALO agent called 'NxtGn Dashboard Agent' with:
- Behavior: [copy behavior prompt from boven]
- Tools: NxtGn API Tool
- Model: gpt-4-1-agentic
- Temperature: 0.4"
```

**Of via HALO Web UI**:
1. Agents → Add Agent
2. Name: "NxtGn Dashboard Agent"  
3. Behavior: [paste behavior prompt]
4. Tools → Add "NxtGn API Tool"
5. Model: gpt-4-1-agentic
6. Save

---

### Stap 6: Testen (5 min)

**Test Scenario 1: List Events**
```
User: "Show me all events"

Expected:
- Agent roept tool aan met endpoint="/events", method="GET"
- Agent toont lijst met 2 events (Summer Festival, Winter Gala)
- Response is conversational, niet raw JSON
```

**Test Scenario 2: Get Statistics**
```
User: "What are the scan statistics for Summer Festival?"

Expected:
- Agent roept tool aan met endpoint="/events/1/stats", method="GET"  
- Agent toont statistieken (3,847 scans, 3,421 inside, etc.)
- Formatted met emojis/structure
```

**Test Scenario 3: Create Entrance Plan**
```
User: "Create an entrance plan for event 1 called Main Gate"

Expected:
- Agent vraagt confirmation (optional)
- Agent roept tool aan met endpoint="/entrance-plans", method="POST", body met event_id en name
- Agent bevestigt successful creation
```

**Verificatie**:
- ✅ Alle 3 scenarios werken
- ✅ Geen 401 authentication errors
- ✅ Response tijd < 3 seconden
- ✅ Agent geeft conversational responses (niet raw JSON)
- ✅ Ngrok dashboard toont requests (http://localhost:4040)

---

## Verificatie Strategie

### Unit Tests (test_api_server.py)

**Handmatig testen met curl**:
```bash
# Health check (no auth)
curl http://localhost:8082/health

# Get events (with auth)
curl -H "Authorization: Bearer test-key-12345" http://localhost:8082/events

# Get specific event
curl -H "Authorization: Bearer test-key-12345" http://localhost:8082/events/1

# Get statistics
curl -H "Authorization: Bearer test-key-12345" http://localhost:8082/events/1/stats

# Create entrance plan
curl -X POST \
  -H "Authorization: Bearer test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"1","name":"Main Gate"}' \
  http://localhost:8082/entrance-plans

# Test wrong token (should 401)
curl -H "Authorization: Bearer wrong-token" http://localhost:8082/events
```

### Integration Tests (HALO Agent)

**Test in Web Conversations**:
1. Start conversation met "NxtGn Dashboard Agent"
2. Test alle 3 use cases (zie Stap 6)
3. Check ngrok dashboard voor request logs
4. Verify responses are conversational

### Debug Tools

1. **Ngrok Dashboard**: http://localhost:4040
   - Zie alle incoming requests
   - Inspect headers, body, response
   - Replay requests voor debugging

2. **Test API Server Logs**:
   - Print statements tonen in terminal waar server draait
   - Zie authenticatie, endpoint matching, errors

3. **HALO Agent Logs**:
   - HALO Web UI → Agent → Conversations → View Details
   - Zie tool calls, parameters, responses

---

## Troubleshooting

### ❌ "Unauthorized" error (401)

**Diagnose**:
```bash
# Check .env token
cat .env | grep TEST_API_INTERNAL_KEY

# Check HALO context variable
# Via /halo: "Get context variable test_api_token"

# Check ngrok dashboard: Is Authorization header correct?
```

**Fix**: Update mismatched token in `.env` of HALO context variable

---

### ❌ Agent niet roept tool aan

**Diagnose**:
- Is tool assigned to agent? (Check HALO UI → Agent → Tools)
- Is tool description duidelijk? (Check Tool → Description)
- Is agent behavior prompt duidelijk over wanneer tool te gebruiken?

**Fix**:
- Update tool description met expliciete voorbeelden
- Update agent behavior met "ALWAYS use NxtGn API Tool when..."
- Test met expliciete command: "Use the NxtGn API Tool to get events"

---

### ❌ Ngrok URL verandert na restart

**Oorzaak**: Gratis ngrok tier = random URL bij elke restart

**Fix (short-term)**:
1. Update HALO context variable `test_api_url` met nieuwe ngrok URL
2. Update `.env` `TEST_API_PUBLIC_URL`

**Fix (long-term)**:
- Deploy naar Glitch/Railway (permanent URL)
- Of: Betaalde ngrok ($8/maand voor static domain)

---

### ❌ Agent toont raw JSON ipv conversational response

**Diagnose**: Agent processed tool response niet conversationally

**Fix**:
1. Update agent behavior: "Present information in clear, conversational way"
2. Check tool configuration: Output moet naar agent gaan (niet direct naar user)
3. Test met expliciete instructie: "Explain the events in a friendly way"

---

## Toekomstige Uitbreidingen

### Fase 2: Permanent Deployment (15 min)

**Glitch deployment** (gratis, aanbevolen):
1. Create account op glitch.com
2. New Project → Import from GitHub (of upload files)
3. Add `requirements.txt`: `python-dotenv`
4. Add environment variables in Glitch UI
5. Krijg permanent HTTPS URL (bijv. `https://nxtgn-test.glitch.me`)
6. Update HALO context variable `test_api_url`

**Railway/Render**: Vergelijkbaar proces, betere performance

---

### Fase 3: Meer Endpoints (5 min per endpoint)

**Patroon**:
```python
# In test_api_server.py, add to do_GET of do_POST:

elif path.startswith('/tickets/'):
    ticket_id = path.split('/')[-1]
    ticket = MOCK_TICKETS.get(ticket_id, None)
    if ticket:
        self._send_json(200, ticket)
    else:
        self._send_json(404, {"error": "Ticket not found"})
```

Geen wijzigingen nodig in HALO tool (generieke tool werkt automatisch)

---

### Fase 4: Real NxtGn API Integratie (1-2 uur)

**Optie A**: Update test_api_server.py om te proxyen naar echte NxtGn API
- Replace mock data met API calls naar Partner API
- Hergebruik Partner API proxy authenticatie

**Optie B**: HALO tool direct naar Partner API proxy wijzen
- Update `test_api_url` context variable naar Partner API URL
- Zelfde tool werkt voor test én productie

**Optie C**: Hybrid (aanbevolen)
- Behoud test server voor development
- Maak tweede context variable set voor productie
- Agent kan switchen tussen test/prod via context

---

## Tijdsinschatting

| Stap | Geschatte tijd | Cumulatief |
|------|----------------|------------|
| 1. Test API server maken | 15 min | 15 min |
| 2. Ngrok setup | 5 min | 20 min |
| 3. HALO context variables | 2 min | 22 min |
| 4. HALO tool maken | 5 min | 27 min |
| 5. HALO agent configureren | 3 min | 30 min |
| 6. Testen & verificatie | 5 min | 35 min |

**Totaal: 35 minuten** (target: 30 min, buffer: 5 min)

---

## Kosten

**POC (dit plan)**: €0
- Python server: gratis
- Ngrok gratis tier: gratis (1 tunnel)
- HALO account: bestaand
- Development tijd: 35 minuten

**Productie (toekomst)**: €0-8/maand
- Glitch gratis tier: €0 (voldoende voor POC)
- Railway gratis tier: €0 ($5 credit/maand)
- Ngrok betaald (optioneel): €8/maand (static domain)

**Antwoord op gebruikers vraag**: Ja, volledig gratis mogelijk met Glitch/Railway + ngrok gratis tiers

---

## Antwoord: "Tool per endpoint?"

**Nee**, je hebt geen aparte tool nodig per endpoint.

**Aanbeveling**: Eén generieke tool met parameters (zoals in dit plan).

**Waarom**:
- Agent is slim genoeg om juiste parameters te kiezen
- Single point of maintenance
- Toevoegen endpoints = geen nieuwe tool nodig
- Flexibeler en schaalbaarder

**Wanneer wel meerdere tools**:
- Heel verschillende functionaliteit (bijv. "Events" vs "Tickets" vs "Users")
- Complexe parameters die sterk verschillen
- Aparte tracking van tool usage nodig

**Hybrid optie** (best of both worlds):
- Generieke tool voor GET (read-only queries)
- Specifieke tools voor POST (create entrance plan, add user, etc.)
- Geeft agent duidelijke action verbs terwijl read flexibility behouden blijft
