# Test MCP Server × HALO Integration

Proof-of-concept voor het testen van HALO agent integratie met een custom API server.

## 📁 Wat zit er in deze map?

- `test_api_server.py` - Python HTTP server met mock NxtGn endpoints
- `test_endpoints.ps1` - PowerShell script om alle endpoints te testen
- `README.md` - Deze documentatie

## 🎯 Doel

Dit project test of een HALO agent via tools succesvol API calls kan maken naar een custom server. Dit is een proof-of-concept voor een "conversational dashboard" waarbij gebruikers via chat acties kunnen uitvoeren.

## 🚀 Quick Start

### 1. Start de server

```powershell
cd "test mcp server x halo"
python test_api_server.py
```

De server draait nu op: http://localhost:8082

### 2. Test de endpoints

```powershell
.\test_endpoints.ps1
```

Of handmatig:

```powershell
# Health check (geen auth)
Invoke-WebRequest -Uri "http://localhost:8082/health" -UseBasicParsing

# Events lijst (met auth)
$headers = @{ "Authorization" = "Bearer test-key-12345" }
Invoke-WebRequest -Uri "http://localhost:8082/events" -Headers $headers -UseBasicParsing
```

### 3. Maak publiek toegankelijk met ngrok

```powershell
ngrok http 8082
```

Kopieer de HTTPS URL (bijv. `https://abc123.ngrok-free.app`)

### 4. Update .env in project root

```env
TEST_API_PUBLIC_URL=https://abc123.ngrok-free.app
```

## 📡 Beschikbare Endpoints

### GET /health
Health check endpoint (geen authenticatie nodig)

**Response:**
```json
{
  "status": "healthy",
  "server": "Test API Server",
  "version": "1.0.0",
  "timestamp": "2026-06-03T13:00:00"
}
```

### GET /events
Lijst alle events

**Headers:**
- `Authorization: Bearer test-key-12345`

**Response:**
```json
{
  "events": [
    {
      "id": "1",
      "name": "Summer Festival 2026",
      "date": "2026-07-15",
      "location": "Amsterdam Arena",
      "capacity": 50000,
      "status": "active"
    },
    {
      "id": "2",
      "name": "Winter Gala",
      "date": "2026-12-20",
      "location": "Rotterdam Ahoy",
      "capacity": 15000,
      "status": "active"
    }
  ],
  "count": 2
}
```

### GET /events/{id}
Details van specifiek event

**Headers:**
- `Authorization: Bearer test-key-12345`

**Response:**
```json
{
  "event": {
    "id": "1",
    "name": "Summer Festival 2026",
    "date": "2026-07-15",
    "location": "Amsterdam Arena",
    "capacity": 50000,
    "status": "active"
  }
}
```

### GET /events/{id}/stats
Scan statistieken voor een event

**Headers:**
- `Authorization: Bearer test-key-12345`

**Response:**
```json
{
  "statistics": {
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
  }
}
```

### POST /entrance-plans
Maak een nieuwe entrance plan aan

**Headers:**
- `Authorization: Bearer test-key-12345`
- `Content-Type: application/json`

**Body:**
```json
{
  "event_id": "1",
  "name": "Main Gate"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Entrance plan \"Main Gate\" created successfully",
  "entrance_plan": {
    "id": "ep_1",
    "event_id": "1",
    "event_name": "Summer Festival 2026",
    "name": "Main Gate",
    "username": "scan_1_DQYn",
    "password": "0Rk6VWOV1vTN",
    "qr_code_url": "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=...",
    "status": "active",
    "created_at": "2026-06-03T13:18:38.687538"
  }
}
```

## 🔐 Authenticatie

Alle endpoints (behalve `/health`) vereisen een Bearer token:

```
Authorization: Bearer test-key-12345
```

Token is geconfigureerd in `../.env`:
```env
TEST_API_INTERNAL_KEY=test-key-12345
```

## 🔗 HALO Integratie

### Stap 1: Context Variables in HALO

Maak in HALO de volgende context variables aan:

```
test_api_url = https://abc123.ngrok-free.app
test_api_token = test-key-12345
```

### Stap 2: HALO Tool maken

**Tool Name:** "NxtGn API Tool"

**Parameters:**
- `endpoint` (string, required) - API path (bijv. "/events")
- `method` (string, required) - HTTP method ("GET" of "POST")
- `body` (string, optional) - JSON body voor POST requests

**HTTP Activity:**
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

### Stap 3: HALO Agent configureren

**Agent Name:** "NxtGn Dashboard Agent"

**Behavior:** Zie complete behavior prompt in het plan bestand

**Tools:** NxtGn API Tool

## 🧪 Testing

### Lokaal testen

```powershell
.\test_endpoints.ps1
```

### Via ngrok testen

```powershell
# Start ngrok in aparte terminal
ngrok http 8082

# Test via ngrok URL
$headers = @{ "Authorization" = "Bearer test-key-12345" }
Invoke-WebRequest -Uri "https://abc123.ngrok-free.app/events" -Headers $headers
```

### Via HALO testen

1. Start conversation met "NxtGn Dashboard Agent"
2. Test: "Show me all events"
3. Test: "What are the scan statistics for event 1?"
4. Test: "Create an entrance plan for event 1 called Main Gate"

## 🚢 Deployment Opties

### Optie A: Ngrok (voor ontwikkeling)
```powershell
ngrok http 8082
```
✅ Snel te testen  
✅ Real-time logs  
❌ URL verandert bij herstart  

### Optie B: Glitch (gratis permanent hosting)
1. Upload `test_api_server.py` naar Glitch
2. Add `requirements.txt`: `python-dotenv`
3. Add environment variables in Glitch UI
4. Krijg permanent URL

✅ Gratis  
✅ Permanent URL  
✅ Geen lokale server nodig  

### Optie C: Railway (gratis tier)
Vergelijkbaar met Glitch, betere performance

## 📊 Status

- ✅ Test API server gemaakt en getest
- ✅ Alle endpoints werkend
- ✅ Authenticatie werkend
- ⏸️ Ngrok setup (handmatige installatie nodig)
- ⏸️ HALO tool maken
- ⏸️ HALO agent configureren
- ⏸️ End-to-end test

## 🔍 Troubleshooting

### Server start niet
```powershell
# Check of poort 8082 al in gebruik is
Get-NetTCPConnection -LocalPort 8082 -ErrorAction SilentlyContinue
```

### 401 Unauthorized
- Check of Authorization header correct is: `Bearer test-key-12345`
- Check of token in `.env` matcht met HALO context variable

### Ngrok URL verandert
- Bij gratis ngrok tier krijg je random URL bij elke restart
- Update HALO context variable `test_api_url` na elke ngrok herstart
- Of: deploy naar Glitch voor permanent URL

## 📚 Referenties

- Volledig plan: `../.claude/plans/maak-een-concreet-plan-splendid-hammock.md`
- Partner API proxy voorbeeld: `../Credentials Halo x NxtGn/partner_api_proxy.py`
- HALO tool patterns: `../.claude/skills/halo/references/tool-patterns.md`

## 💰 Kosten

- Python server: €0 (gratis)
- Ngrok gratis tier: €0
- Glitch gratis tier: €0
- Railway gratis tier: €0 ($5 credit/maand)

**Totaal: €0** ✅
