# Deployment Information

## Public URL
*(Điền URL public sau khi deploy `06-lab-complete/` lên Railway hoặc Render)*

## Platform
Railway / Render

## Test Commands

### Health & Readiness Check
```bash
BASE="https://your-agent.railway.app"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"   # Expected: 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"    # Expected: 200
```

### API Test (Authentication)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'                               # Expected: 401

curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question": "Hello"}'                               # Expected: 200
```

## Environment Variables Set
- `PORT` (do nền tảng cấp tự động)
- `ENVIRONMENT=production`
- `REDIS_URL` (trỏ tới Redis service trên nền tảng)
- `AGENT_API_KEY` (đặt trên nền tảng, không ghi trong code)
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
