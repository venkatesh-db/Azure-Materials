"""Reliability at scale (Feature 15): a real, runnable load test against
the deployed Function App — NOT literally the capstone's 12,000 TPS
figure. That number is a narrative prompt for architecture discussion,
not something to actually fire at a personal Azure subscription (it would
cost real money and likely get rate-limited/throttled by Azure itself
well before 12,000 TPS on a Consumption-plan Function App, which has a
documented ~200 concurrent-instance soft limit).

This script runs a real, honest, modest concurrent load test (default
50 requests, 10 concurrent) against the deployed executor endpoint,
measures actual p50/p95/p99 latency and error rate, and reports whether
observed throughput and error rate would need architectural changes to
approach the capstone's stated numbers — that's the correct use of a
load test at this scale: informing the discussion, not literally
reproducing a number that isn't a real target for a Consumption-plan demo
environment.
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def send_one(url: str, function_key: str, idempotency_key: str) -> tuple[float, int]:
    start = time.perf_counter()
    try:
        resp = requests.post(
            url, params={"code": function_key},
            json={"idempotency_key": idempotency_key, "service_name": "load-test-service", "environment": "production"},
            timeout=30,
        )
        status = resp.status_code
    except requests.RequestException:
        status = -1
    latency_ms = (time.perf_counter() - start) * 1000
    return latency_ms, status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--function-app-name", required=True)
    parser.add_argument("--function-key", required=True)
    parser.add_argument("--total-requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()

    url = f"https://{args.function_app_name}.azurewebsites.net/api/request-service-restart"
    print(f"Load test: {args.total_requests} requests, {args.concurrency} concurrent, against {url}")
    print("(All requests use no approval_token, so every one should correctly return 403 — "
          "this tests the endpoint's throughput/latency under load, not a real restart storm.)\n")

    latencies = []
    statuses = []
    start_time = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(send_one, url, args.function_key, f"load-test-{i}")
            for i in range(args.total_requests)
        ]
        for future in as_completed(futures):
            latency_ms, status = future.result()
            latencies.append(latency_ms)
            statuses.append(status)

    total_time_s = time.perf_counter() - start_time
    observed_throughput = args.total_requests / total_time_s
    error_count = sum(1 for s in statuses if s not in (200, 201, 403))  # 403 is the EXPECTED response here

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]

    print(f"Total time: {total_time_s:.2f}s")
    print(f"Observed throughput: {observed_throughput:.1f} requests/sec")
    print(f"Latency — p50: {p50:.0f}ms  p95: {p95:.0f}ms  p99: {p99:.0f}ms  mean: {statistics.mean(latencies):.0f}ms")
    print(f"Unexpected errors: {error_count}/{args.total_requests}")
    print(f"Status code distribution: {sorted(set(statuses))}")

    print("\n--- Honest scale assessment ---")
    print(f"Observed: ~{observed_throughput:.0f} req/s on a Consumption-plan Function App with "
          f"{args.concurrency} concurrent callers.")
    print("Capstone target: 12,000 TPS. Getting there is NOT a code change to this script — it needs:")
    print("  - Premium or Dedicated (App Service) plan instead of Consumption (removes cold-start + concurrency caps)")
    print("  - Horizontal scale-out with pre-warmed instances")
    print("  - The idempotency/approval-token store (currently SQLite) moved to Cosmos DB or similar, "
          "since SQLite is not safe for concurrent multi-instance writes at this scale")
    print("  - Load testing from a proper tool (Azure Load Testing / k6) with distributed load generators, "
          "not a single-process ThreadPoolExecutor")


if __name__ == "__main__":
    main()
