# fetcher/topic_tagger.py
#
# WHY THIS FILE EXISTS:
# Before we have the Claude API (Subsystem 2), we need a lightweight way to tag articles.
# This is the "good enough for now" version — keyword matching.
# It deliberately keeps tagging fast, free, and offline.
#
# SYSTEM DESIGN PRINCIPLE AT PLAY:
# Progressive enhancement. Start simple (keyword matching), instrument it, THEN
# upgrade to AI-based tagging when you can measure whether it's worth the cost.
# This is how Netflix evolved their recommendation engine — rules first, then ML.

# Topic map: system design interview topic -> keywords that suggest it
# WHY keywords over ML here? This runs on EVERY article, potentially hundreds per day.
# A Claude API call costs money and time. Keywords cost nothing and run in microseconds.
TOPIC_KEYWORDS = {
    "caching": [
        "cache", "redis", "memcached", "eviction", "lru", "ttl", "cdn cache",
        "invalidation", "write-through", "write-back", "cache miss", "cache hit"
    ],
    "rate-limiting": [
        "rate limit", "throttle", "token bucket", "leaky bucket", "sliding window",
        "quota", "429", "api limit", "rate control", "backpressure"
    ],
    "distributed-systems": [
        "consensus", "raft", "paxos", "zookeeper", "distributed", "eventual consistency",
        "cap theorem", "partition", "replication", "leader election", "quorum"
    ],
    "databases": [
        "sql", "nosql", "postgres", "mysql", "cassandra", "dynamodb", "sharding",
        "indexing", "query optimization", "transactions", "acid", "b-tree", "lsm"
    ],
    "messaging-queues": [
        "kafka", "rabbitmq", "sqs", "pub/sub", "event streaming", "message queue",
        "consumer group", "offset", "topic partition", "dead letter"
    ],
    "microservices": [
        "microservice", "service mesh", "istio", "grpc", "api gateway", "sidecar",
        "circuit breaker", "service discovery", "container", "docker", "kubernetes"
    ],
    "load-balancing": [
        "load balancer", "round robin", "least connections", "nginx", "haproxy",
        "health check", "sticky session", "layer 7", "layer 4", "traffic distribution"
    ],
    "observability": [
        "monitoring", "tracing", "logging", "metrics", "prometheus", "grafana",
        "opentelemetry", "distributed tracing", "alert", "slo", "sla", "latency p99"
    ],
    "ml-systems": [
        "machine learning", "model serving", "feature store", "training pipeline",
        "recommendation", "embeddings", "inference", "mlflow", "model drift"
    ],
    "search": [
        "elasticsearch", "search index", "inverted index", "full-text search",
        "relevance", "ranking", "vector search", "lucene", "solr", "tfidf"
    ],
    "real-time-systems": [
        "real-time", "low latency", "streaming", "websocket", "event-driven",
        "flink", "spark streaming", "change data capture", "cdc"
    ],
    "storage-systems": [
        "object storage", "s3", "hdfs", "blob storage", "file system",
        "block storage", "replication factor", "erasure coding", "data lake"
    ],
    "api-design": [
        "rest", "graphql", "api versioning", "idempotency", "pagination",
        "webhook", "openapi", "grpc", "swagger", "backward compatibility"
    ],
    "security": [
        "oauth", "jwt", "authentication", "authorization", "encryption",
        "tls", "ssl", "zero trust", "secrets management", "ddos"
    ],
    "chaos-engineering": [
        "chaos", "fault injection", "resilience", "failover", "disaster recovery",
        "game day", "chaos monkey", "bulkhead", "graceful degradation"
    ],
}


def tag_article(title: str, summary: str) -> list[str]:
    """
    Tags an article with system design topics based on keyword matching.

    WHY return a LIST of tags?
    A single article can teach multiple concepts. A Netflix post about
    "how we migrated from monolith to microservices" might cover:
    microservices + databases + observability + load-balancing.
    You want to surface it when the user filters for ANY of those.

    WHY lowercase the text once?
    Performance. If you have 500 articles and 300 keywords, that's 150,000
    comparisons. Doing .lower() inside the inner loop doubles the cost for no reason.
    This is micro-optimization but it's the right habit.
    """
    text = (title + " " + summary).lower()
    matched_tags = []

    for topic, keywords in TOPIC_KEYWORDS.items():
        # Check if ANY keyword for this topic appears in the article text
        # WHY 'any()' instead of a loop? It short-circuits — stops checking
        # the moment it finds a match. Same result, slightly faster.
        if any(kw in text for kw in keywords):
            matched_tags.append(topic)

    # If nothing matched, return a fallback tag so the article isn't lost
    # WHY not just return []? Empty-tagged articles disappear from filtered views.
    # 'general' is a catch-all bucket you can manually review later.
    return matched_tags if matched_tags else ["general"]


def filter_by_topic(articles: list[dict], topic: str) -> list[dict]:
    """
    Filter a list of articles to only those tagged with a given topic.
    This powers the 'interview prep mode' — user picks a topic, gets relevant articles.

    INTERVIEW INSIGHT:
    This is a simplified version of what LinkedIn's Skills Graph does —
    mapping content to structured skill/topic taxonomies for personalized feeds.
    """
    if topic == "all":
        return articles
    return [a for a in articles if topic in a.get("tags", [])]


def get_all_topics() -> list[str]:
    """Returns sorted list of all available interview topics."""
    return sorted(TOPIC_KEYWORDS.keys())
