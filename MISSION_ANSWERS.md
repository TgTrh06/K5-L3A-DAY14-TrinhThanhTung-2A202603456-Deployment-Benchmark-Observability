# Day 14 Lab — Mission Answers

> **Họ và tên:** Trịnh Thanh Tùng  
> **MSSV:** 2A202603456  
> **Lớp:** K5-L3A  

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong source code** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`. Nếu push lên GitHub sẽ lộ ngay lập tức.
2. **Không quản lý cấu hình qua biến môi trường** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` được gán cứng, không tách biệt cấu hình giữa `development` / `staging` / `production`.
3. **Dùng `print()` và log lộ secret** (dòng 33–34, 38): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` vừa không theo cấu trúc JSON để log aggregator (Loki/Datadog) phân tích, vừa in thẳng API key ra stdout.
4. **Thiếu Health Check / Readiness endpoint** (dòng 42–43): Không có `GET /health` hay `GET /ready`, nên nền tảng cloud/orchestrator không biết container còn sống hay đã sẵn sàng nhận traffic.
5. **Bind cứng `host="localhost"`, `port=8000` và bật `reload=True`** (dòng 49–53): `localhost` chỉ nhận kết nối từ bên trong máy/container (không truy cập được từ ngoài container), `port=8000` không đọc `PORT` do Railway/Render cấp, và `reload=True` không an toàn/tốn tài nguyên ở production.
6. **Không có Graceful Shutdown**: Tắt process đột ngột sẽ cắt ngang request đang xử lý và không đóng kết nối tài nguyên.

### Exercise 1.2 & 1.3: Bảng so sánh `develop/app.py` và `production/app.py`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py`) | Tại sao quan trọng? |
| :--- | :--- | :--- | :--- |
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG = True` | Đọc qua `settings` từ biến môi trường (`.env` / env vars) | Tránh lộ secret trên Git, thay đổi cấu hình không cần sửa code (12-Factor). |
| **Health check** | Không có `/health` | Có `GET /health` (uptime, version, env) và readiness flag `is_ready` | Orchestrator/Cloud dùng probe để tự restart container lỗi và điều hướng traffic. |
| **Logging** | `print("[DEBUG] ...")`, in cả API key | `logging` định dạng JSON (`{"time":...,"level":...,"msg":...}`), không log secret | Dễ tìm kiếm, lọc và cảnh báo trên hệ thống tập trung (Grafana Loki, Datadog). |
| **Network & Port** | `host="localhost"`, `port=8000`, `reload=True` | Đọc `PORT` từ env, chạy qua `0.0.0.0` | Bắt buộc để container nhận traffic từ bên ngoài và tương thích Railway/Render. |
| **Shutdown** | Tắt đột ngột | Dùng `lifespan` context manager để dọn dẹp khi shutdown | Hoàn thành request đang xử lý (in-flight) trước khi thoát, tránh lỗi 502 cho user. |
| **Input & CORS** | Nhận `question` qua query param, không CORS | Nhận JSON body, validate 422, cấu hình `CORSMiddleware` | Chuẩn hóa API contract và kiểm soát origin được phép gọi. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Trả lời 4 câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` (bản đầy đủ trên Debian, dung lượng lớn ~1 GB).
2. **Working directory là gì?** `/app` (`WORKDIR /app`).
3. **Tại sao `COPY requirements.txt` trước `COPY . .`?** Để tận dụng **Docker layer cache**: khi chỉ sửa source code (`app.py`), layer cài `pip install -r requirements.txt` không bị invalidate nên build lại rất nhanh.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?** `ENTRYPOINT` định nghĩa tiến trình chính cố định của container, còn `CMD` cung cấp tham số mặc định cho `ENTRYPOINT` (hoặc lệnh mặc định nếu không có `ENTRYPOINT`) và dễ bị ghi đè khi truyền tham số lúc `docker run`.

### Exercise 2.2 & 2.3: So sánh kích thước Image đo được

Build từ gốc repository:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
docker images my-agent --format "{{.Repository}}:{{.Tag}} -> {{.Size}}"
```

Kết quả đo thực tế trên máy:
- **Develop (`my-agent:develop`):** `1.67 GB` (~1670 MB)
- **Production (`my-agent:advanced`):** `240 MB`
- **Chênh lệch:** Giảm **~85.6%** dung lượng (nhỏ hơn ~6.96 lần).

**Giải thích multi-stage (`02-docker/production/Dockerfile`):**
- **Stage 1 (`builder`):** Dùng `python:3.11-slim`, cài `gcc`, `libpq-dev` và `pip install --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`):** Dùng `python:3.11-slim` sạch, chỉ `COPY --from=builder /root/.local /home/appuser/.local`, tạo user non-root `appuser`, thêm `HEALTHCHECK` và chạy `uvicorn`. Nhờ loại bỏ compiler (`gcc`, `libpq-dev`, apt cache) ở image cuối nên dung lượng giảm mạnh và an toàn hơn.

### Exercise 2.4: Kiến trúc Docker Compose (`02-docker/production/docker-compose.yml`)

```text
Client ──► Nginx (:80) ──► Agent (:8000, internal) ──► Redis (:6379, session/rate-limit)
                                                   └──► Qdrant (:6333, vector DB)
```

- Stack gồm 4 services trên mạng nội bộ `internal`: `nginx` (reverse proxy/load balancer mở cổng 80/443), `agent` (build target `runtime`, `depends_on` `redis` và `qdrant` ở trạng thái `service_healthy`), `redis` (`redis:7-alpine`), và `qdrant` (`qdrant/qdrant:v1.9.0`).

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 lên Cloud

- **Nền tảng chính:** Railway
- **Public URL:** https://06-lab-complete-production-255d551f.up.railway.app (chi tiết lệnh test xem [DEPLOYMENT.md](DEPLOYMENT.md))
- **Ảnh chụp:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` | `render.yaml` (Blueprint) |
| :--- | :--- | :--- |
| **Mục đích** | Cấu hình build & deploy cho 1 service trên Railway | Khai báo Infrastructure-as-Code cho 1 hoặc nhiều services + env vars trên Render |
| **Chỉ định Docker** | `[build]` với `builder = "DOCKERFILE"` | `runtime: docker` trong mục `services` |
| **Health check** | `[deploy]` với `healthcheckPath = "/health"` | `healthCheckPath: /health` |
| **Quản lý biến môi trường / Secret** | Thường đặt trên Railway Dashboard hoặc CLI | Có thể khai báo trực tiếp trong `envVars` với `generateValue: true` (tự sinh secret) hoặc `sync: false` (nhập tay trên dashboard, không lộ trong Git) |

### Exercise 3.3: Mô tả pipeline CI/CD Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Dựa trên `cloudbuild.yaml` và `service.yaml`, pipeline CI/CD trên Google Cloud Build thực hiện tuần tự 4 bước khi có push lên nhánh `main`:
1. **`test`:** Dùng image `python:3.11-slim` để cài `requirements.txt` + `pytest` và chạy toàn bộ unit tests (`pytest tests/ -v`).
2. **`build`:** Dùng `gcr.io/cloud-builders/docker` build image gắn tag `$COMMIT_SHA` và `latest` (tận dụng `--cache-from`).
3. **`push`:** Đẩy các tag image vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** Dùng `gcloud run deploy ai-agent` triển khai lên Cloud Run (`asia-southeast1`, `min-instances=1`, `max-instances=10`, memory `512Mi`), inject secret (`OPENAI_API_KEY`) từ Secret Manager; kết hợp `service.yaml` cấu hình `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1–4.3: Kết quả test Security (`04-api-gateway/production/app.py`)

- **Algorithm trong `rate_limiter.py`:** **Sliding Window Counter** sử dụng `collections.deque` lưu timestamp các request trong cửa sổ `window_seconds = 60`.
- **Giới hạn:** User thường (`rate_limiter_user`) là **10 requests/phút**; Admin (`rate_limiter_admin`) là **100 requests/phút** (hoặc có thể kiểm tra `role == "admin"` để bypass/nâng hạn mức).

Kết quả chạy thực tế với tài khoản `student` (đã che token):
```text
# 1. Gọi POST /ask không có token:
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# 2. Lấy JWT qua POST /auth/token (student / demo123):
HTTP/1.1 200 OK  (nhận access_token, đã che)

# 3. Gọi vòng lặp POST /ask với Header "Authorization: Bearer <REDACTED_TOKEN>":
Request 1..10 -> HTTP/1.1 200 OK
Request 11    -> HTTP/1.1 429 Too Many Requests
Retry-After: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Giải thích cách làm Cost Guard

- **Tại sao cần cả Rate Limit và Cost Guard?** Rate limit bảo vệ **tốc độ** (chống spam/DDoS theo số request/phút), còn Cost Guard bảo vệ **ngân sách tiền** (vì một câu hỏi dài vẫn có thể tốn nhiều token dù gọi chậm).
- **Cách triển khai với Redis:** Trước khi gọi LLM (`check_budget`), đọc tổng chi phí hiện tại trong Redis theo key ngày/tháng (ví dụ `cost:daily:YYYY-MM-DD` hoặc `cost:monthly:YYYY-MM`). Nếu `current >= budget` → trả về **HTTP 402 Payment Required**. Sau khi gọi LLM xong (`record_cost`), tính chi phí theo số `input_tokens` và `output_tokens` rồi cộng dồn bằng `INCRBYFLOAT` kèm `EXPIRE` tự dọn key cũ.

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5: Ghi chú triển khai & Kết quả test Stateless

1. **Liveness (`/health`) vs Readiness (`/ready`):**
   - `/health` kiểm tra **process còn sống không** — luôn trả `200` khi app chạy (kể cả khi Redis tạm mất), để orchestrator không restart vô ích.
   - `/ready` kiểm tra **app có sẵn sàng nhận traffic không** (ping Redis) — trả `503` khi mất kết nối Redis để Load Balancer tạm ngừng điều hướng traffic tới instance đó.
2. **Graceful Shutdown:** Khi nhận `SIGTERM`, app ngừng nhận kết nối mới, hoàn thành các request đang xử lý (in-flight), đóng kết nối Redis rồi thoát với exit code `0`.
3. **Stateless Design:** Không lưu `conversation_history` hay rate-limit counter trong RAM (vì khi scale nhiều instance, mỗi instance có RAM riêng). Mọi state được đưa về **Redis** dùng chung.

**Kết quả chạy thực tế `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python test_stateless.py`:**
```text
Session ID: 9f18d950-1bc2-4bf3-b89a-c7fc5de7fa67

Request 1: [instance-c04173]  Q: What is Docker?
Request 2: [instance-6cae12]  Q: Why do we need containers?
Request 3: [instance-901b5f]  Q: What is Kubernetes?
Request 4: [instance-c04173]  Q: How does load balancing work?
Request 5: [instance-6cae12]  Q: What is Redis used for?

Total requests: 5
Instances used: {'instance-6cae12', 'instance-901b5f', 'instance-c04173'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```
**Giải thích:** Nginx phân tải 5 request lần lượt qua cả 3 container agent khác nhau (`instance-c04173`, `instance-6cae12`, `instance-901b5f`), nhưng toàn bộ 10 tin nhắn (5 user + 5 assistant) vẫn được lưu đầy đủ và đọc lại chính xác nhờ lưu state tập trung trên Redis.

---

## Part 6: Output `check_production_ready.py`

*(Kết quả kiểm tra đầy đủ trên Windows + Docker: 42/42 checks passed, image size 56 MB, `docker stop` 1.2s exit code 0; kiểm tra `SIGTERM` runtime trên Linux container `--skip-docker` cũng đạt exit code 0. Chạy `python check_production_ready.py` trong WSL2 sẽ báo `PASS 12/12`.)*

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown (Docker stop exit 0, 1.2s; POSIX SIGTERM exit 0)
     ✅ Public URL ready (Railway / Render config)
```

---

## AI Usage Log

- **Công cụ sử dụng:** Antigravity AI Assistant.
- **Mục đích:** Hỗ trợ phân tích yêu cầu lab, hoàn thiện các module `TODO` trong `06-lab-complete/`, chạy các bài kiểm tra Docker/benchmark và tổng hợp số liệu thực tế vào báo cáo. Sinh viên đã kiểm tra, hiểu rõ và xác nhận toàn bộ kết quả chạy trên máy.
