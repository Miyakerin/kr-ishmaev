"""In-memory mock telemetry for the PolicyConsistency monitoring dashboard."""

from collections import deque
from datetime import datetime, timezone
import random
import threading
import time


SAMPLE_INTERVAL_SECONDS = 3
RETENTION_SECONDS = 24 * 60 * 60
WINDOWS = {
    "30s": 30,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "24h": 24 * 60 * 60,
}

RECENT_EVENT_TEXT = {
    "conflict": [
        ("Конфликт ролей при обновлении политики", "PolicyConsistency"),
        ("Обнаружено пересечение правил доступа", "PolicyConsistency"),
        ("Несогласованная политика помещена в карантин", "PolicyConsistency"),
        ("Конфликт наследования прав", "PolicyConsistency"),
    ],
    "denied": [
        ("Запрос заблокирован: недостаточно прав", "PDP · HTTP 403"),
        ("Отказ в доступе к таблице customer_data", "PDP · HTTP 403"),
        ("Попытка чтения без разрешения", "PDP · HTTP 403"),
        ("Запрос отклонён политикой безопасности", "PDP · HTTP 403"),
    ],
}


class MockTelemetry:
    """Generate one consistent stream of mock service and policy telemetry."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started_at = time.time()
        self.next_sample_at = self.started_at
        self.samples = deque()
        self.events = deque(maxlen=250)
        self.status = {"hadoop": True, "policy": True}
        self.recover_at = {"hadoop": 0.0, "policy": 0.0}
        self.load_metrics = {
            "requestsPerSecond": random.uniform(32, 78),
            "hadoopCpu": random.uniform(24, 56),
            "hadoopRam": random.uniform(42, 74),
            "policyCpu": random.uniform(12, 38),
            "policyRam": random.uniform(28, 60),
        }
        self._record_sample(self.started_at)

    @staticmethod
    def _now_iso(timestamp):
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()

    def _roll_status(self, key, now, outage_chance):
        if not self.status[key] and now >= self.recover_at[key]:
            self.status[key] = True
        elif self.status[key] and random.random() < outage_chance:
            self.status[key] = False
            self.recover_at[key] = now + random.randint(2, 5) * SAMPLE_INTERVAL_SECONDS
        return self.status[key]

    def _record_sample(self, timestamp):
        hadoop_up = self._roll_status("hadoop", timestamp, 0.004)
        policy_up = self._roll_status("policy", timestamp, 0.006)
        ranger_up = random.random() > 0.012
        hdfs_up = hadoop_up
        acl_up = random.random() > 0.008
        hive_up = random.random() > 0.012

        conflict_count = random.choices([0, 1, 2, 3], [0.48, 0.35, 0.14, 0.03])[0]
        denied_count = (
            random.choices([0, 1, 2, 3, 4], [0.25, 0.30, 0.25, 0.15, 0.05])[0]
            if policy_up else 0
        )
        self._advance_load_metrics()

        sample = {
            "timestamp": timestamp,
            "conflicts": conflict_count,
            "denied": denied_count,
            "hadoop": hadoop_up,
            "policy": policy_up,
            "ranger": ranger_up,
            "hdfs": hdfs_up,
            "acl": acl_up,
            "hive": hive_up,
            **self.load_metrics,
        }
        self.samples.append(sample)

        for _ in range(conflict_count):
            title, source = random.choice(RECENT_EVENT_TEXT["conflict"])
            self._add_event(timestamp, "conflict", title, source, None)
        for _ in range(denied_count):
            title, source = random.choice(RECENT_EVENT_TEXT["denied"])
            self._add_event(timestamp, "denied", title, source, 403)

    def _advance_load_metrics(self):
        bounds = {
            "requestsPerSecond": (8, 160, 14),
            "hadoopCpu": (12, 92, 8),
            "hadoopRam": (32, 90, 2.5),
            "policyCpu": (6, 86, 8),
            "policyRam": (22, 82, 2.5),
        }
        for name, (minimum, maximum, jitter) in bounds.items():
            self.load_metrics[name] = round(
                min(maximum, max(minimum, self.load_metrics[name] + random.uniform(-jitter, jitter))),
                1,
            )
        if random.random() < 0.08:
            self.load_metrics["requestsPerSecond"] = round(
                min(160, self.load_metrics["requestsPerSecond"] + random.uniform(12, 36)),
                1,
            )

    def _add_event(self, timestamp, kind, title, source, status_code):
        self.events.appendleft({
            "id": f"{kind}-{timestamp:.3f}-{random.randrange(100000)}",
            "timestamp": timestamp,
            "time": datetime.fromtimestamp(timestamp, timezone.utc).strftime("%H:%M:%S"),
            "kind": kind,
            "title": title,
            "source": source,
            "status": status_code,
        })

    def _advance(self, now):
        if now - self.next_sample_at > RETENTION_SECONDS:
            self.next_sample_at = now - RETENTION_SECONDS
        while self.next_sample_at <= now:
            self._record_sample(self.next_sample_at)
            self.next_sample_at += SAMPLE_INTERVAL_SECONDS

        cutoff = now - RETENTION_SECONDS
        while self.samples and self.samples[0]["timestamp"] < cutoff:
            self.samples.popleft()

    @staticmethod
    def _uptime(samples, key):
        if not samples:
            return 100.0
        return round(sum(1 for sample in samples if sample[key]) / len(samples) * 100, 2)

    def snapshot(self, window="15m"):
        if window not in WINDOWS:
            window = "15m"
        now = time.time()
        cutoff = now - WINDOWS[window]
        with self.lock:
            self._advance(now)
            samples = list(self.samples)
            window_samples = [item for item in samples if item["timestamp"] >= cutoff]
            current = samples[-1]
            buckets = 30
            bucket_width = WINDOWS[window] / buckets
            load_metric_names = (
                "requestsPerSecond",
                "hadoopCpu",
                "hadoopRam",
                "policyCpu",
                "policyRam",
            )
            chart = [
                {
                    "conflicts": 0,
                    "denied": 0,
                    "samples": 0,
                    **{name: 0.0 for name in load_metric_names},
                }
                for _ in range(buckets)
            ]
            for sample in window_samples:
                index = min(
                    buckets - 1,
                    max(0, int((sample["timestamp"] - cutoff) / bucket_width)),
                )
                chart[index]["conflicts"] += sample["conflicts"]
                chart[index]["denied"] += sample["denied"]
                chart[index]["samples"] += 1
                for name in load_metric_names:
                    chart[index][name] += sample[name]

            for bucket in chart:
                count = bucket.pop("samples")
                for name in load_metric_names:
                    bucket[name] = (
                        round(bucket[name] / count, 1)
                        if count else None
                    )

            latest_minute = [item for item in samples if item["timestamp"] >= now - 60]
            session_samples = samples
            events = [
                {**event, "time": datetime.fromtimestamp(
                    event["timestamp"], timezone.utc
                ).astimezone().strftime("%H:%M:%S")}
                for event in list(self.events)[:8]
            ]
            return {
                "generatedAt": self._now_iso(now),
                "sessionSeconds": max(0, int(now - self.started_at)),
                "window": window,
                "metrics": {
                    "conflicts": sum(item["conflicts"] for item in window_samples),
                    "denied": sum(item["denied"] for item in window_samples),
                    "conflictsPerMinute": round(
                        sum(item["conflicts"] for item in latest_minute), 1
                    ),
                    "deniedPerMinute": round(
                        sum(item["denied"] for item in latest_minute), 1
                    ),
                    "requestsPerSecond": current["requestsPerSecond"],
                },
                "services": {
                    "hadoop": {
                        "up": current["hadoop"],
                        "uptime": self._uptime(window_samples, "hadoop"),
                    },
                    "policy": {
                        "up": current["policy"],
                        "uptime": self._uptime(window_samples, "policy"),
                    },
                },
                "sync": {
                    "ranger": current["ranger"],
                    "hdfs": current["hdfs"],
                    "acl": current["acl"],
                    "hive": current["hive"],
                },
                "chart": chart,
                "events": events,
                "sessionUptime": {
                    "hadoop": self._uptime(session_samples, "hadoop"),
                    "policy": self._uptime(session_samples, "policy"),
                },
            }


telemetry = MockTelemetry()