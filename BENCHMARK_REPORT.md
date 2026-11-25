# Benchmark & Observability Report — Day 14

**Họ tên:** Trịnh Thanh Tùng (MSSV: `2A202603456` — K5-L3A)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11, Docker Desktop (Docker `29.5.3`, Compose `v5.1.4`), Python `3.12.6`

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
| :--- | :--- | :--- |
| p95 latency `/ask` | `< 500 ms` | Với mock LLM có base latency ~120ms + jitter + retrieval, 95% request bình thường hoàn thành dưới 250ms; ngưỡng 500ms đảm bảo trải nghiệm chat mượt mà. |
| Error rate `/ask` | `< 2.0 %` | `MOCK_ERROR_RATE` mặc định là 1% (0.01); đặt SLO 2% giúp phát hiện ngay khi upstream LLM lỗi bất thường hoặc quá tải. |
| Accuracy trên golden dataset | `≥ 85 %` | Đảm bảo chất lượng RAG của agent v2 đạt mức tin cậy trước khi cho phép deploy (dùng quality gate chặn merge nếu tụt accuracy). |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

*(Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` — mỗi mức 300 requests)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO (`p95 ≤ 500ms`, `err ≤ 2%`) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | 4.08 | 194.7 | 234.6 | 1710.9 | 0.33% | PASS |
| 10 | 44.44 | 190.4 | 234.5 | 1704.8 | 0.67% | PASS |
| 50 | 90.10 | 215.8 | 979.1 | 1713.9 | 2.33% | FAIL |
| 100 | 42.70 | 991.5 | 4960.3 | 5317.6 | 0.67% | FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính theo concurrency. Từ concurrency 1 → 10 → 50, RPS tăng từ `4.08` lên `44.44` rồi `90.10` req/s nhờ I/O bất đồng bộ (`asyncio`), nhưng đến concurrency 100 thì RPS **giảm xuống `42.70` req/s** và `p95` vọt lên `4960.3 ms` do event loop/single-process uvicorn bị bão hòa và hàng đợi request tăng cao.

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

*(Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
| :---: | :---: | :---: | :---: |
| `0` | 186.8 | 220.2 | 228.6 |
| `0.03` (mặc định) | 232.7 | 229.4 | 1711.5 |
| `0.1` | 277.4 | 1652.0 | 1718.2 |

**Nhận xét:** **p95 và p99** nhạy nhất với request chậm: khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03`, `avg` chỉ tăng nhẹ từ `186.8 ms` lên `232.7 ms` (trông có vẻ bình thường), nhưng `p99` nhảy vọt từ `228.6 ms` lên `1711.5 ms` (gấp 7.5 lần); đến `0.1` thì cả `p95` cũng vọt lên `1652.0 ms`. Vì vậy SLO **không nên đặt theo average**, vì giá trị trung bình che giấu trải nghiệm tệ của nhóm người dùng gặp tail latency.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
| :--- | :---: | :---: | :---: |
| **Accuracy** | 4.35% (1/23) | 91.30% (21/23) | 100.0% (23/23) |
| **Avg tokens / câu** | 56.5 | 109.3 | 113.4 |
| **Tổng cost (USD)** | \$0.000396 | \$0.000764 | \$0.000789 |
| **Cost / câu đúng (USD)** | \$0.00039615 | \$0.00003639 | \$0.00003429 |
| **Quality gate** | FAIL | PASS (`≥ 80%`) | PASS (`≥ 100%`, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách đã sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
| :--- | :--- | :--- |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry `(["jwt", "xác thực"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "kubernetes"], ...)` vào `KNOWLEDGE_BASE`. |

**Nhận xét trade-off & Quality gate trong CI:**
- Agent v2 tốn nhiều token hơn v1 (`109.3` vs `56.5` tokens/câu) và tổng cost cao hơn gần gấp đôi (`$0.000764` vs `$0.000396`) do có thêm bước retrieval context vào prompt. Tuy nhiên, **cost / câu đúng** của v2 (`$0.00003639`) rẻ hơn v1 (`$0.00039615`) **hơn 10 lần**, vì v1 trả lời sai 22/23 câu nên tiền bỏ ra bị lãng phí.
- **Dùng exit code trong CI/CD:** `eval/run_eval.py --min-accuracy 0.85 --baseline reports/eval_v2.json` trả **exit code 1** nếu `accuracy < --min-accuracy` hoặc có bất kỳ câu nào bị regression so với baseline. Đưa bước này vào GitHub Actions / Cloud Build sẽ tự động chặn merge PR khi chất lượng agent bị giảm.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] `screenshots/grafana-dashboard.png` — Dashboard Grafana khi đang có tải
- [x] `screenshots/jaeger-slow-trace.png` — Một trace chậm trong Jaeger
- [x] `screenshots/jaeger-error-trace.png` — Một trace lỗi trong Jaeger (có event `exception`)
- [x] `screenshots/prometheus-alert-firing.png` — Trang Alerts của Prometheus thấy ≥ 2 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống" (dựa trên `prometheus/alert_rules.yml`)

| # | Thay đổi | Alert nào firing | Thời gian `for` (cấu hình) | Panel nào phản ánh rõ nhất |
| :---: | :--- | :--- | :---: | :--- |
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`> 5%`) | `1m` | Error Rate (5xx %) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`p95 > 1s`) | `2m` | Request Latency (p50 / p95 / p99) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`> $2/giờ`) | `2m` | LLM Cost Burn Rate |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`up == 0`) | `30s` | Active Instances / Up |
| E | `AGENT_VERSION=v1` | *(Không có alert nào firing)* | — | — |

**Thí nghiệm E không làm alert nào firing. Cách phát hiện sự cố này trong production:**
- Alert hạ tầng (latency, error rate, CPU, RAM) đều xanh vì v1 vẫn trả HTTP 200 nhanh, nhưng **chất lượng câu trả lời tụt từ ~100% xuống 4.3%**.
- Để phát hiện sớm trong production cần: (1) chạy **quality eval trên golden dataset** trong CI/CD trước khi deploy (chặn ngay ở quality gate), và (2) theo dõi thêm metric nghiệp vụ/chất lượng như tỷ lệ fallback response, user feedback (thumbs down), hoặc chạy online LLM-as-a-judge trên một tỷ lệ nhỏ traffic thật.

### 4.3 Debug bằng trace

Trace chậm thu được trong phiên chạy Locust trên stack `k5-day14-observability`:

- **`trace_id`:** `4dccfebe712545692b60f97d98aebecc`
- **Tổng thời gian:** `1708.6 ms`
- **Span chiếm nhiều thời gian nhất:** `llm_call` (`1680.8 ms`, chiếm **98.4%** tổng thời gian request)
- **Dòng log JSON tương ứng (khớp `trace_id`):**

```json
{"ts": "2026-11-25T16:22:51.067593+00:00", "level": "INFO", "service": "observable-agent", "instance": "5d804a3b5f4a", "event": "http_request", "trace_id": "4dccfebe712545692b60f97d98aebecc", "span_id": "85e6ef84774eaa36", "request_id": "f5b2d641c61a", "method": "POST", "route": "/ask", "status": 200, "ms": 1708.6}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Nguồn: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` — dòng `/ask`)*

| Số instance | Tổng req `/ask` | RPS (`/ask`) | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `1` | 7137 | 59.75 | 190 | 260 | 1700 | 86 |
| `3` | 7178 | 60.10 | 190 | 230 | 1700 | 64 |

**Giải thích kết quả:**
- Khi scale từ 1 lên 3 instance, **p95 giảm nhẹ từ `260 ms` xuống `230 ms`** do giảm bớt tranh chấp CPU/event loop trên mỗi container, nhưng **RPS gần như giữ nguyên (~60 req/s)** và **p99 vẫn là `1700 ms`**.
- **Nút thắt nằm ở 2 chỗ:** (1) Với bài test 100 users mà mỗi user trong `locustfile.py` có `wait_time` giữa các request, tổng tải sinh ra bị giới hạn ở ~60 RPS (chưa làm bão hòa 3 instance); và (2) `p99 = 1700 ms` đến từ **tail latency nội tại của mock LLM (`MOCK_SLOW_MS = 1500 ms`)** — việc thêm instance không làm cho một lần gọi upstream LLM chậm chạy nhanh hơn được.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. Không đánh giá hiệu năng bằng latency trung bình (`avg`); phải dùng `p95`/`p99` để nhìn thấy tail latency ảnh hưởng tới người dùng thật.
  2. Monitoring hạ tầng (Prometheus + Grafana) không đủ bắt lỗi suy giảm chất lượng AI; cần kết hợp **eval trên golden dataset** làm quality gate trong CI/CD.
  3. Gắn `trace_id` xuyên suốt OpenTelemetry → Jaeger → Structured JSON logs giúp truy vết chính xác nguyên nhân một request chậm hoặc lỗi chỉ trong vài giây.
- **Nếu đưa lên production thật, sẽ thêm metric/alert:**
  - Alert theo **Token/Request bất thường** (phát hiện prompt injection hoặc vòng lặp agent) và **Quality/Fallback rate** (phát hiện RAG retrieval trả về rỗng tăng đột biến).
