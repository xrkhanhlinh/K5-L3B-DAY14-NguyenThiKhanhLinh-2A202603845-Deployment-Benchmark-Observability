# Benchmark & Observability Report - Day 14

**Ho ten:** Nguyen Thi Khanh Linh

**Run dates:** 2026-11-26 to 2026-11-27 (GMT+7)

Environment: Windows, Python 3.11.9; Docker Desktop Linux, 8 CPUs, 3,982,716,928 bytes memory. Other applications and Docker builds were running during local measurements; these are observations under that contention, not isolated capacity limits.

## 1. SLO

| SLI | Target | Reason |
|---|---|---|
| /ask p95 | <=500 ms | Lab responsiveness goal |
| /ask error rate | <=2% | Default mock faults ~1%; allow limited failures |
| Golden dataset accuracy | 100% after KB fix | All 23 lab cases, no regression |

## 2. Performance

### 2.1 Concurrency

| Concurrency | RPS | p50 ms | p95 ms | p99 ms | Errors | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.63 | 214.1 | 323.7 | 1731.6 | 1.00% | PASS |
| 10 | 34.98 | 206.7 | 427.5 | 1741.6 | 1.00% | PASS |
| 50 | 18.6 | 1073.1 | 7931.5 | 8143.6 | 2.00% | FAIL |
| 100 | 30.52 | 1732.4 | 6843.2 | 7263.7 | 0.33% | FAIL |

RPS is not linear: client scheduling, logging, CPU/disk contention and upstream latency affect throughput. SLO failures are preserved in the JSON, not replaced by estimates. Latency percentiles in load_test.py include successful HTTP 200 requests only; error rate covers all requests.

### 2.2 Tail latency

| MOCK_SLOW_RATE | avg ms | p95 ms | p99 ms |
|---|---|---|---|
| 0 | 258.7 | 524.3 | 609.6 |
| 0.03 | 302.2 | 587.9 | 1742.8 |
| 0.1 | 406.3 | 1733.5 | 1906.1 |

Each run used 300 requests and concurrency 20, with default random error rate 0.01. A slow minority increases p99 while the average dilutes it. At 10% slow calls, p95 also rises. Random sampling and host contention explain differences beyond the injected delay.

## 3. Quality evaluation

| Metric | v1 | v2 baseline | v2 fixed |
|---|---|---|---|
| Accuracy | 0.0435 | 0.913 | 1.0 |
| Passed / 23 | 1 | 21 | 23 |
| Avg tokens | 57.0 | 108.8 | 113.0 |
| Total mock USD | 0.000403 | 0.000757 | 0.000784 |
| USD / correct answer | 0.00040275 | 3.607e-05 | 3.41e-05 |
| Quality gate | FAIL | PASS | PASS |

Evaluation used MOCK_ERROR_RATE=0. The unchanged dataset has 23 cases; per-answer pass requires at least 60% expected keywords. v1/v2 were measured before changing the KB. Added JWT token/expiry/signature and HPA CPU/memory/custom-metrics documents in both KB copies. v2 fixed achieved 23/23 with no regressions against eval_v2.json. Retrieval adds context, tokens and latency; compare USD/correct answer rather than USD/request alone. Mock cost is simulated, not a provider bill.

| Failed baseline case | Missing keywords | KB change |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Added JWT definition, expiry and signature verification |
| scaling-03 | cpu, memory, custom metrics | Added HPA scaling signals |

## 4. Observability stack

Stack verified: Nginx, 3 instrumented agent containers, Prometheus, Grafana, Jaeger and Locust. Prometheus discovered all 3 agent targets as up. Existing `promtool test rules` returned SUCCESS. Values below were collected from Prometheus/Jaeger HTTP APIs and Docker JSON logs. Grafana was captured with live traffic at approximately 07:40 GMT+7 on November 27. The remaining three UI screenshots were captured with Playwright using the existing Chrome installation, after explicit user authorization, at approximately 07:57–08:00 GMT+7. The Jaeger images show the same trace IDs analyzed below; the Prometheus image shows both required alerts firing together.

### 4.1 Required screenshots

- [x] [Grafana with traffic](screenshots/grafana-dashboard.png)
- [x] [Jaeger slow trace with expanded LLM span](screenshots/jaeger-slow-trace.png)
- [x] [Jaeger error trace with exception event](screenshots/jaeger-error-trace.png)
- [x] [Prometheus with two simultaneous firing alerts](screenshots/prometheus-alert-firing.png)

### 4.2 Chaos experiments

| Experiment | Configuration | Expected alert | Measured time |
|---|---|---|---|
| A | MOCK_ERROR_RATE=0.2 | AgentHighErrorRate | 104.3 s; observed 18:01:53.999 UTC; Error rate panel |
| B | MOCK_SLOW_RATE=0.3 | AgentHighLatencyP95 | 159.9 s; observed 18:02:49.579 UTC; Latency p95 panel |
| C | LLM_MODEL=mock-llm-large | LLMCostBurnRateHigh | Model change not performed; cost alert already fired during baseline Locust load |
| D | Pause one instance | AgentInstanceDown | Not performed; expected after scrape failure + 30 s hold |
| E | AGENT_VERSION=v1 | None for infrastructure | Not performed on this stack; v1's poor quality was measured in section 3 |

A and B were injected together at `2026-11-26T18:00:09.7194483+00:00`, using the original rules unchanged. They are simultaneous fault scenarios, not isolated estimates of each fault's effect. Ten concurrent clients maintained traffic. Polling every 5 s recorded the first observed firing times; polling and API latency limit timing precision. Error alert activeAt was 18:00:47.401817116 UTC (1 minute hold), latency alert activeAt 18:00:42.401817116 UTC (2 minute hold). Both were firing together by 18:02:49.579 UTC. LLMCostBurnRateHigh was also firing, but its activeAt predates injection (17:56:42.571501534 UTC), so it is not counted as a newly triggered chaos result.

Agent recreation briefly produced 1782 proxy HTTP 502 responses before DNS refreshed. These were excluded from agent-side counters because requests did not reach the app. At the later Prometheus snapshot, agent-side error rate was 20.22%, consistent with the 20% injection. The report therefore does not use the client's cumulative error fraction as the injected error rate.

Changing to v1 can degrade answer quality without affecting latency/error alerts. Detect this with fixed-dataset eval and, for real traffic, monitored quality samples. A 504 generated by Nginx may not appear in agent counters; monitor the proxy or use synthetic checks too.

### 4.3 Trace analysis

Jaeger sample: 500 trace summaries after injection, filtered to complete `POST /ask` traces. The slowest complete trace found in this sample:

- `trace_id`: `8daf8be9aac2edb98cfdf892d7d11024`.
- Total: 1777.074 ms; parent `agent.run`: 1771.614 ms.
- Dominant leaf span: `chat mock-llm-small`, 1751.698 ms (98.57% of total); retrieval 19.538 ms. Parent durations contain child durations and must not be added to them.
- Matching Docker log:

```json
{"ts":"2026-11-26T18:03:50.681080+00:00","level":"INFO","service":"observable-agent","instance":"faf773afccca","event":"http_request","trace_id":"8daf8be9aac2edb98cfdf892d7d11024","span_id":"d30e3b1d9a70f236","request_id":"0ed1a059e2cb","method":"POST","route":"/ask","status":200,"ms":1775.5}
```

Error trace `9e75e5d6e8bba880095a76e410dd1734` contains an `exception` event in the LLM span, type `utils.mock_llm.LLMError`, message `Upstream LLM error: 503 Service Unavailable (mock)`; the API returns sanitized HTTP 503. Matching log:

```json
{"ts":"2026-11-26T18:03:48.304116+00:00","level":"INFO","service":"observable-agent","instance":"faf773afccca","event":"llm_error","trace_id":"9e75e5d6e8bba880095a76e410dd1734","span_id":"c533a90abcfa8f5f","request_id":"89eada36ab1b","error":"Upstream LLM error: 503 Service Unavailable (mock)"}
```

The mock log's `llm_ms=1635.2` reports its configured simulated sleep, while the measured LLM span was 1751.698 ms including actual scheduling/processing overhead. Use request/span wall time to assess real latency under contention. Trace search used `GET /api/v3/trace-summaries`, with detailed trace retrieval from `/api/traces/{id}` supported by this Jaeger version; see [Jaeger APIs](https://www.jaegertracing.io/docs/2.23/architecture/apis/).

### 4.4 Exercise 7.4

- Prometheus snapshot at `2026-11-26T18:03:56.064016+00:00`, using 1 minute rates: /ask traffic 16.56 RPS, errors 20.22%, average 597.33 ms, histogram p95 1899.77 ms. The tail is much larger than the average. Histogram quantiles are bucket estimates; they differ from Locust's client-side percentiles and this is a separate chaos workload.
- Per-instance /ask RPS: `172.21.0.4:8000` = 5.5125, `172.21.0.8:8000` = 5.5125, `172.21.0.9:8000` = 5.5306. This window shows nearly even Nginx distribution.
- Input token rate was 950.98/s versus output 528.32/s. Input includes system prompt, retrieved context and question; output covers the answer only. Rates count completed successful LLM calls in this app.
- Nginx returns 404 for /metrics by design; Prometheus scrapes agent containers directly on the internal network.

## 5. Scaling benchmark

Locust headless, 100 users, ramp 10/s, 2 minutes per run. Both runs used defaults MOCK_ERROR_RATE=0.01, MOCK_SLOW_RATE=0.03, mock-llm-small, v2. Each agent has a 0.5 CPU / 256 MiB limit; all services share the same Docker VM. Health was checked before each run.

| Instances | RPS | p50 ms | p95 ms | p99 ms | Failures / requests |
|---|---:|---:|---:|---:|---:|
| 1 | 62.19 | 200 | 830 | 2400 | 77 / 7022 (1.10%) |
| 3 | 62.52 | 200 | 1200 | 2100 | 57 / 7412 (0.77%) |

These are the `Aggregated` rows in [scale_1_stats.csv](benchmark-results/scale_1_stats.csv) and [scale_3_stats.csv](benchmark-results/scale_3_stats.csv), including /health. For /ask alone: 1 instance = 56.64 RPS, p50 210 ms, p95 990 ms, p99 2500 ms, 77/6396 failures; 3 instances = 56.83 RPS, p50 200 ms, p95 1300 ms, p99 2100 ms, 57/6738 failures. Failures were mock HTTP 503; /health had zero failures. Locust percentiles include failures; the develop load-test percentiles include only successful responses.

Scaling did not improve p95 in these runs. Throughput increased only 0.54%; p99 improved, but p95 worsened. With fixed 100 users, think time 0.5–2 seconds, shared host resources and upstream mock delays, increasing replicas cannot guarantee linear RPS. These measurements do not isolate a single bottleneck or prove a maximum capacity; a sustained-load sweep with resource profiles would be needed.

Commands, from the production directory:
```bash
docker compose -p k5-day14-observability up -d --build --scale agent=1
# Wait for stable /health and Docker DNS refresh.
docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_1
docker compose -p k5-day14-observability up -d --scale agent=3
# Wait for stable /health and Docker DNS refresh.
docker compose -p k5-day14-observability run --rm --no-deps locust -f /mnt/locust/locustfile.py --host http://nginx --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_3
```
`--no-deps` is intentional: otherwise `compose run` restores the dependency's default two replicas and invalidates the one-instance comparison. The initial run affected by this and startup 502/504 responses was discarded; the submitted CSVs are from completed reruns with the correct replica counts.

## 6. Lessons and final review

1. Successful HTTP responses do not prove semantic correctness.
2. Average latency hides outliers; report p95/p99 and errors together.
3. Cost per correct answer captures the retrieval trade-off better than cost per call.

For a real deployment: add proxy/synthetic availability metrics, request queue saturation, quality regression checks and strict atomic budget reservations. The unchanged lab error alert fires above 5%, which is looser than this report's 2% error SLO; production rules should also detect sustained SLO/error-budget burn below 5%.

Render is live and rechecked 200/200/401/200 after updating the repository URL (see DEPLOYMENT.md). Full Linux/Docker checker passed 12/12, fixed eval passed 23/23, both scaling CSVs and actual trace/alert measurements are complete. All seven required screenshots are present and visually reviewed. Grafana and Prometheus screenshots were captured during later replays of the same fault workload, so live panel values and alert activeAt timestamps differ from the earlier API snapshot and timing experiment above. The cost alert was inactive in the later Prometheus screenshot; error rate and latency alerts were both firing. No screenshot content was fabricated or changed.

After collecting evidence, the load generator was stopped and `docker compose -p k5-day14-observability down -v` completed. Other pre-existing project containers remained healthy. The Render deployment remains available for grading.
