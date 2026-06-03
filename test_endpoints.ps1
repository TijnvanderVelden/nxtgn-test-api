# Test script voor Test API Server endpoints
# Run: .\test_endpoints.ps1

$ErrorActionPreference = "Stop"

$baseUrl = "http://localhost:8082"
$token = "test-key-12345"
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "Test API Server - Endpoint Tests" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan

# Test 1: Health check (no auth)
Write-Host "[TEST 1] GET /health (no auth)" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/health" -UseBasicParsing
    $data = $response.Content | ConvertFrom-Json
    Write-Host "  ✓ Status: $($data.status)" -ForegroundColor Green
    Write-Host "  ✓ Server: $($data.server)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 2: Get all events
Write-Host "[TEST 2] GET /events" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/events" -Headers $headers -UseBasicParsing
    $data = $response.Content | ConvertFrom-Json
    Write-Host "  ✓ Count: $($data.count) events" -ForegroundColor Green
    foreach ($event in $data.events) {
        Write-Host "    - $($event.name) ($($event.date))" -ForegroundColor Gray
    }
} catch {
    Write-Host "  ✗ FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 3: Get specific event
Write-Host "[TEST 3] GET /events/1" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/events/1" -Headers $headers -UseBasicParsing
    $data = $response.Content | ConvertFrom-Json
    Write-Host "  ✓ Event: $($data.event.name)" -ForegroundColor Green
    Write-Host "  ✓ Location: $($data.event.location)" -ForegroundColor Green
    Write-Host "  ✓ Capacity: $($data.event.capacity)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 4: Get event statistics
Write-Host "[TEST 4] GET /events/1/stats" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/events/1/stats" -Headers $headers -UseBasicParsing
    $data = $response.Content | ConvertFrom-Json
    $stats = $data.statistics
    Write-Host "  ✓ Total scans: $($stats.total_scans)" -ForegroundColor Green
    Write-Host "  ✓ Unique visitors: $($stats.unique_visitors)" -ForegroundColor Green
    Write-Host "  ✓ Currently inside: $($stats.currently_inside)" -ForegroundColor Green
    Write-Host "  ✓ Capacity: $($stats.capacity_percentage)%" -ForegroundColor Green
} catch {
    Write-Host "  ✗ FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 5: Create entrance plan
Write-Host "[TEST 5] POST /entrance-plans" -ForegroundColor Yellow
try {
    $body = @{
        event_id = "1"
        name = "Test Entrance $(Get-Random -Maximum 1000)"
    } | ConvertTo-Json

    $response = Invoke-WebRequest -Uri "$baseUrl/entrance-plans" -Method POST -Headers $headers -Body $body -UseBasicParsing
    $data = $response.Content | ConvertFrom-Json
    $plan = $data.entrance_plan
    Write-Host "  ✓ Created: $($plan.name)" -ForegroundColor Green
    Write-Host "  ✓ Plan ID: $($plan.id)" -ForegroundColor Green
    Write-Host "  ✓ Username: $($plan.username)" -ForegroundColor Green
    Write-Host "  ✓ Password: $($plan.password)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 6: Authentication test (wrong token)
Write-Host "[TEST 6] Authentication test (wrong token)" -ForegroundColor Yellow
try {
    $wrongHeaders = @{ "Authorization" = "Bearer wrong-token" }
    $response = Invoke-WebRequest -Uri "$baseUrl/events" -Headers $wrongHeaders -UseBasicParsing
    Write-Host "  ✗ FAILED: Should have returned 401" -ForegroundColor Red
} catch {
    if ($_.Exception.Message -match "401") {
        Write-Host "  ✓ Correctly rejected with 401 Unauthorized" -ForegroundColor Green
    } else {
        Write-Host "  ✗ FAILED: Wrong error - $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""

# Test 7: Invalid event ID
Write-Host "[TEST 7] GET /events/999 (non-existent)" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$baseUrl/events/999" -Headers $headers -UseBasicParsing
    Write-Host "  ✗ FAILED: Should have returned 404" -ForegroundColor Red
} catch {
    if ($_.Exception.Message -match "404") {
        Write-Host "  ✓ Correctly returned 404 Not Found" -ForegroundColor Green
    } else {
        Write-Host "  ✗ FAILED: Wrong error - $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "All tests completed!" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan
