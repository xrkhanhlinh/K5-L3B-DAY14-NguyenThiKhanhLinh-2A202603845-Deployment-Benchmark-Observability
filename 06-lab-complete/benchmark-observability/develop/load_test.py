"""
Load test đơn giản — benchmark HIỆU NĂNG của agent.

Gửi request song song tới POST /ask và báo cáo:
  • Throughput (RPS)
  • Error rate
  • Latency: min / avg / p50 / p90 / p95 / p99 / max
  • So sánh với SLO → PASS / FAIL

Ví dụ:
  python load_test.py --url http://localhost:8000 --requests 200 --concurrency 10
  python load_test.py --duration 30 --concurrency 20 --out reports/load_v2.json
  python load_test.py --slo-p95-ms 500 --slo-error-rate 0.01

Vì sao cần p95/p99 mà không chỉ average?
  → 100 request: 97 cái mất 150ms, 3 cái mất 1.7s
    average ≈ 200ms (trông ổn) nhưng p99 ≈ 1.7s (3% user chờ gần 2 giây!)
"""
import argparse
import asyncio
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

import httpx

QUESTIONS = [
    "Docker container là gì?",
    "Readiness probe khác gì liveness probe?",
    "Vì sao nên dùng p95 thay vì latency trung bình?",
    "Prometheus thu thập metric như thế nào?",
    "Graceful shutdown hoạt động ra sao khi nhận SIGTERM?",
    "Tính chi phí token của LLM như thế nào?",
]


def percentile(sorted_values: list[float], p: float) -> float:
    """Percentile theo nội suy tuyến tính (giống numpy.percentile mặc định)."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


async def worker(client: httpx.AsyncClient, url: str, headers: dict, results: list,
                 stop_at: float | None, counter: dict, total: int | None):
    while True:
        if stop_at is not None and time.perf_counter() >= stop_at:
            return
        if total is not None:
            if counter["sent"] >= total:
                return
            counter["sent"] += 1

        payload = {"question": random.choice(QUESTIONS)}
        start = time.perf_counter()
        try:
            resp = await client.post(f"{url}/ask", json=payload, headers=headers)
            status = resp.status_code
            cost = resp.json().get("usage", {}).get("cost_usd", 0.0) if status == 200 else 0.0
        except httpx.HTTPError as exc:
            status, cost = f"conn_error:{type(exc).__name__}", 0.0
        results.append({"status": status, "latency_ms": (time.perf_counter() - start) * 1000,
                        "cost_usd": cost})


async def run(args) -> dict:
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    results: list[dict] = []
    counter = {"sent": 0}
    stop_at = time.perf_counter() + args.duration if args.duration else None
    total = None if args.duration else args.requests

    limits = httpx.Limits(max_connections=args.concurrency)
    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as client:
        # Warm-up: request đầu tiên thường chậm (kết nối, cache...) → không tính
        try:
            await client.post(f"{args.url}/ask", json={"question": "warm up"}, headers=headers)
        except httpx.HTTPError as exc:
            raise SystemExit(f"❌ Không kết nối được {args.url}: {exc}")

        started = time.perf_counter()
        await asyncio.gather(*[
            worker(client, args.url, headers, results, stop_at, counter, total)
            for _ in range(args.concurrency)
        ])
        elapsed = time.perf_counter() - started

    latencies = sorted(r["latency_ms"] for r in results if r["status"] == 200)
    status_counts = Counter(str(r["status"]) for r in results)
    errors = sum(1 for r in results if r["status"] != 200)

    return {
        "target": args.url,
        "concurrency": args.concurrency,
        "total_requests": len(results),
        "duration_s": round(elapsed, 2),
        "rps": round(len(results) / elapsed, 2) if elapsed else 0,
        "error_rate": round(errors / len(results), 4) if results else 0,
        "status_codes": dict(status_counts),
        "latency_ms": {
            "min": round(latencies[0], 1) if latencies else 0,
            "avg": round(sum(latencies) / len(latencies), 1) if latencies else 0,
            "p50": round(percentile(latencies, 50), 1),
            "p90": round(percentile(latencies, 90), 1),
            "p95": round(percentile(latencies, 95), 1),
            "p99": round(percentile(latencies, 99), 1),
            "max": round(latencies[-1], 1) if latencies else 0,
        },
        "total_cost_usd": round(sum(r["cost_usd"] for r in results), 6),
    }


def print_report(report: dict, slo_p95_ms: float, slo_error_rate: float) -> bool:
    lat = report["latency_ms"]
    print("\n" + "═" * 56)
    print(f"  LOAD TEST REPORT — {report['target']}")
    print("═" * 56)
    print(f"  Requests     : {report['total_requests']}  (concurrency={report['concurrency']})")
    print(f"  Duration     : {report['duration_s']} s")
    print(f"  Throughput   : {report['rps']} req/s")
    print(f"  Error rate   : {report['error_rate'] * 100:.2f}%   {report['status_codes']}")
    print(f"  Total cost   : ${report['total_cost_usd']}")
    print("  Latency (ms) : "
          f"min={lat['min']}  avg={lat['avg']}  max={lat['max']}")
    print(f"                 p50={lat['p50']}  p90={lat['p90']}  "
          f"p95={lat['p95']}  p99={lat['p99']}")
    print("─" * 56)

    p95_ok = lat["p95"] <= slo_p95_ms
    err_ok = report["error_rate"] <= slo_error_rate
    print(f"  SLO p95 ≤ {slo_p95_ms:.0f}ms        : {'✅ PASS' if p95_ok else '❌ FAIL'}")
    print(f"  SLO error rate ≤ {slo_error_rate * 100:.1f}%  : {'✅ PASS' if err_ok else '❌ FAIL'}")
    print("═" * 56 + "\n")
    return p95_ok and err_ok


def main():
    parser = argparse.ArgumentParser(description="Load test cho AI agent")
    parser.add_argument("--url", default=os.getenv("AGENT_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("AGENT_API_KEY"))
    parser.add_argument("--requests", type=int, default=200, help="Tổng số request")
    parser.add_argument("--duration", type=float, help="Chạy theo thời gian (giây) thay vì số request")
    parser.add_argument("--concurrency", type=int, default=10, help="Số request song song")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--slo-p95-ms", type=float, default=500)
    parser.add_argument("--slo-error-rate", type=float, default=0.02)
    parser.add_argument("--out", help="Lưu report JSON vào file")
    args = parser.parse_args()

    report = asyncio.run(run(args))
    passed = print_report(report, args.slo_p95_ms, args.slo_error_rate)
    report["slo"] = {"p95_ms": args.slo_p95_ms, "error_rate": args.slo_error_rate, "passed": passed}

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"💾 Đã lưu report: {args.out}")

    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
