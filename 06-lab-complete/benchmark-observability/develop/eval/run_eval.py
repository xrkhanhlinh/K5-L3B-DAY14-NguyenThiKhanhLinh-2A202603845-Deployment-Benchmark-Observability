"""
Eval chất lượng — benchmark ĐỘ CHÍNH XÁC của agent trên golden dataset.

Load test trả lời câu hỏi "agent có NHANH không?".
Eval trả lời câu hỏi "agent có ĐÚNG không?" — và có tệ đi sau lần thay đổi này không?

Cách chấm (keyword-based, đơn giản, chạy offline):
  score = số expected_keywords xuất hiện trong câu trả lời / tổng số keywords
  pass  = score >= --pass-threshold (mặc định 0.6)

Trong thực tế có thể thay bằng: exact match, semantic similarity, hoặc LLM-as-judge.

Ví dụ:
  python eval/run_eval.py --out reports/eval_v1.json                 # agent v1 đang chạy
  python eval/run_eval.py --out reports/eval_v2.json \
         --baseline reports/eval_v1.json                             # so sánh v2 với v1
  python eval/run_eval.py --min-accuracy 0.85                        # quality gate cho CI

Exit code 1 nếu accuracy < --min-accuracy hoặc có regression so với baseline
→ dùng được làm bước "quality gate" trong CI/CD trước khi deploy.
"""
import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path

import httpx

DEFAULT_DATASET = Path(__file__).parent / "golden_dataset.jsonl"


def load_dataset(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def score_answer(answer: str, expected_keywords: list[str]) -> tuple[float, list[str]]:
    answer_lower = answer.lower()
    missing = [kw for kw in expected_keywords if kw.lower() not in answer_lower]
    return 1 - len(missing) / len(expected_keywords), missing


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def ask(client: httpx.Client, url: str, question: str, headers: dict, retries: int) -> dict:
    """Gọi agent; retry khi lỗi 5xx tạm thời (LLM upstream lỗi ngẫu nhiên)."""
    for attempt in range(retries + 1):
        start = time.perf_counter()
        try:
            resp = client.post(f"{url}/ask", json={"question": question}, headers=headers)
            latency_ms = (time.perf_counter() - start) * 1000
            if resp.status_code == 200:
                return {"ok": True, "data": resp.json(), "latency_ms": latency_ms}
            error = f"HTTP {resp.status_code}"
            if resp.status_code < 500:
                break  # lỗi 4xx: retry cũng vô ích
        except httpx.HTTPError as exc:
            latency_ms, error = (time.perf_counter() - start) * 1000, type(exc).__name__
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))
    return {"ok": False, "error": error, "latency_ms": latency_ms}


def run_eval(args) -> dict:
    dataset = load_dataset(Path(args.dataset))
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    results = []

    with httpx.Client(timeout=args.timeout) as client:
        for item in dataset:
            res = ask(client, args.url, item["question"], headers, args.retries)
            if res["ok"]:
                data = res["data"]
                score, missing = score_answer(data["answer"], item["expected_keywords"])
                results.append({
                    "id": item["id"], "category": item["category"],
                    "passed": score >= args.pass_threshold, "score": round(score, 2),
                    "missing_keywords": missing, "latency_ms": round(res["latency_ms"], 1),
                    "cost_usd": data["usage"]["cost_usd"],
                    "tokens": data["usage"]["input_tokens"] + data["usage"]["output_tokens"],
                    "agent_version": data.get("agent_version"), "answer": data["answer"][:160],
                })
            else:
                results.append({
                    "id": item["id"], "category": item["category"], "passed": False,
                    "score": 0.0, "error": res["error"], "latency_ms": round(res["latency_ms"], 1),
                    "cost_usd": 0.0, "tokens": 0,
                })
            mark = "✅" if results[-1]["passed"] else "❌"
            print(f"  {mark} {item['id']:<16} score={results[-1]['score']:.2f}  "
                  f"{results[-1]['latency_ms']:>7.1f}ms")

    by_cat = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        by_cat[r["category"]]["total"] += 1
        by_cat[r["category"]]["passed"] += int(r["passed"])

    passed = sum(r["passed"] for r in results)
    latencies = sorted(r["latency_ms"] for r in results if "error" not in r)
    total_cost = sum(r["cost_usd"] for r in results)
    versions = {r.get("agent_version") for r in results if r.get("agent_version")}

    return {
        "target": args.url,
        "agent_version": ", ".join(sorted(versions)) or "unknown",
        "dataset": str(args.dataset),
        "total": len(results),
        "passed": passed,
        "accuracy": round(passed / len(results), 4) if results else 0,
        "avg_score": round(sum(r["score"] for r in results) / len(results), 4) if results else 0,
        "errors": sum(1 for r in results if "error" in r),
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 1),
            "p95": round(percentile(latencies, 95), 1),
        },
        "total_cost_usd": round(total_cost, 6),
        "avg_tokens": round(sum(r["tokens"] for r in results) / len(results), 1) if results else 0,
        # "Chi phí cho mỗi câu trả lời ĐÚNG" — chỉ số tốt để so sánh 2 phiên bản
        "cost_per_correct_usd": round(total_cost / passed, 8) if passed else None,
        "by_category": {k: {**v, "accuracy": round(v["passed"] / v["total"], 2)}
                        for k, v in sorted(by_cat.items())},
        "results": results,
    }


def _usd(value) -> str:
    return f"${value:.8f}" if value is not None else "n/a"


def compare_with_baseline(report: dict, baseline: dict) -> list[str]:
    """In bảng so sánh và trả về danh sách câu bị regression (baseline đúng → giờ sai)."""
    def delta(key, fmt="{:+.1%}", sub=None):
        cur = report[key] if sub is None else report[key][sub]
        old = baseline[key] if sub is None else baseline[key][sub]
        diff = fmt.format(cur - old) if cur is not None and old is not None else "n/a"
        return cur, old, diff.replace("%", " điểm %") if key == "accuracy" else diff

    print(f"\n  📊 So sánh với baseline (agent {baseline['agent_version']})")
    print(f"  {'Chỉ số':<22}{'Baseline':>12}{'Hiện tại':>12}{'Thay đổi':>16}")
    rows = [
        ("Accuracy", *delta("accuracy"), "{:.1%}"),
        ("Latency p95 (ms)", *delta("latency_ms", "{:+.1f}", "p95"), "{:.1f}"),
        ("Avg tokens / câu", *delta("avg_tokens", "{:+.1f}"), "{:.1f}"),
        ("Tổng cost (USD)", *delta("total_cost_usd", "{:+.6f}"), "{:.6f}"),
    ]
    for name, cur, old, d, fmt in rows:
        print(f"  {name:<22}{fmt.format(old):>12}{fmt.format(cur):>12}{d:>16}")

    old_pass = {r["id"] for r in baseline["results"] if r["passed"]}
    regressions = [r["id"] for r in report["results"] if r["id"] in old_pass and not r["passed"]]
    fixed = [r["id"] for r in report["results"] if r["id"] not in old_pass and r["passed"]]
    print(f"\n  ✨ Câu được cải thiện : {len(fixed)}")
    print(f"  ⚠️  Câu bị regression : {len(regressions)} {regressions if regressions else ''}")
    return regressions


def main():
    parser = argparse.ArgumentParser(description="Eval chất lượng agent trên golden dataset")
    parser.add_argument("--url", default=os.getenv("AGENT_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("AGENT_API_KEY"))
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--pass-threshold", type=float, default=0.6)
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--baseline", help="Report JSON của phiên bản trước để so sánh")
    parser.add_argument("--out", help="Lưu report JSON vào file")
    args = parser.parse_args()

    print(f"\n🧪 Eval agent tại {args.url}\n")
    report = run_eval(args)

    print("\n" + "═" * 58)
    print(f"  EVAL REPORT — agent {report['agent_version']}")
    print("═" * 58)
    print(f"  Accuracy      : {report['accuracy']:.1%}  ({report['passed']}/{report['total']})")
    print(f"  Errors        : {report['errors']}")
    print(f"  Latency (ms)  : p50={report['latency_ms']['p50']}  p95={report['latency_ms']['p95']}")
    print(f"  Avg tokens    : {report['avg_tokens']}")
    print(f"  Total cost    : ${report['total_cost_usd']}   "
          f"(cost / câu đúng: {_usd(report['cost_per_correct_usd'])})")
    print("  Theo category :")
    for cat, v in report["by_category"].items():
        print(f"    - {cat:<14} {v['passed']}/{v['total']}  ({v['accuracy']:.0%})")

    regressions = []
    if args.baseline:
        regressions = compare_with_baseline(report, json.loads(Path(args.baseline).read_text(encoding="utf-8")))

    gate_ok = report["accuracy"] >= args.min_accuracy and not regressions
    print("─" * 58)
    print(f"  Quality gate (accuracy ≥ {args.min_accuracy:.0%}, không regression): "
          f"{'✅ PASS' if gate_ok else '❌ FAIL'}")
    print("═" * 58 + "\n")

    report["quality_gate"] = {"min_accuracy": args.min_accuracy, "regressions": regressions,
                              "passed": gate_ok}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"💾 Đã lưu report: {args.out}")

    raise SystemExit(0 if gate_ok else 1)


if __name__ == "__main__":
    main()
