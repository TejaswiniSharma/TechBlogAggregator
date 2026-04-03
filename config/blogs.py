# config/blogs.py
#
# WHY THIS FILE EXISTS:
# Separating configuration from logic is a core engineering principle (12-Factor App).
# If you hardcode blog URLs inside your fetcher, changing them means touching business logic.
# Here, adding a new blog = one line. Removing one = delete one line.
# This also makes it easy for future Subsystem 2 (AI Tagger) to know which COMPANY wrote each article.

BLOGS = [
    # Format: { name, company, rss_url, tags_hint }
    # tags_hint = what system design topics this blog is MOST known for
    # (used by Subsystem 2 later as context when asking Claude to tag articles)

    {
        "name": "Netflix Tech Blog",
        "company": "Netflix",
        "rss_url": "https://netflixtechblog.com/feed",
        "tags_hint": ["microservices", "chaos-engineering", "streaming", "availability"],
    },
    {
        "name": "LinkedIn Engineering",
        "company": "LinkedIn",
        # LinkedIn does not publish an RSS feed — scraped from the listing page instead.
        "scrape_url": "https://www.linkedin.com/blog/engineering/",
        "tags_hint": ["distributed-systems", "data-infrastructure", "ml-at-scale", "search"],
    },
    {
        "name": "Uber Engineering",
        "company": "Uber",
        "rss_url": "https://www.uber.com/en-US/blog/engineering/rss/",
        "tags_hint": ["real-time-systems", "geospatial", "high-availability", "data-pipelines"],
    },
    {
        "name": "Airbnb Engineering",
        "company": "Airbnb",
        "rss_url": "https://medium.com/feed/airbnb-engineering",
        "tags_hint": ["search", "pricing-systems", "open-source", "data-platform"],
    },
    {
        "name": "Spotify Engineering",
        "company": "Spotify",
        "rss_url": "https://engineering.atspotify.com/feed/",
        "tags_hint": ["data-pipelines", "machine-learning", "recommendation-systems"],
    },
    {
        "name": "Meta Engineering",
        "company": "Meta",
        "rss_url": "https://engineering.fb.com/feed/",
        "tags_hint": ["large-scale-infra", "ai-ml", "open-source", "social-graph"],
    },
    {
        "name": "Stripe Engineering",
        "company": "Stripe",
        "rss_url": "https://stripe.com/blog/engineering/rss",
        "tags_hint": ["api-design", "payments", "reliability", "distributed-transactions"],
    },
    {
        "name": "DoorDash Engineering",
        "company": "DoorDash",
        "rss_url": "https://doordash.engineering/feed/",
        "tags_hint": ["logistics", "real-time-dispatch", "microservices", "ml-ops"],
    },
    {
        "name": "Shopify Engineering",
        "company": "Shopify",
        "rss_url": "https://engineering.shopify.com/blogs/engineering.atom",
        "tags_hint": ["scalability", "ecommerce", "ruby-rails", "infrastructure"],
    },
    {
        "name": "Cloudflare Blog",
        "company": "Cloudflare",
        "rss_url": "https://blog.cloudflare.com/rss/",
        "tags_hint": ["cdn", "networking", "edge-computing", "security", "dns"],
    },
    {
        "name": "AWS Architecture Blog",
        "company": "AWS",
        "rss_url": "https://aws.amazon.com/blogs/architecture/feed/",
        "tags_hint": ["cloud-architecture", "serverless", "databases", "scalability"],
    },
    {
        "name": "Dropbox Tech Blog",
        "company": "Dropbox",
        "rss_url": "https://dropbox.tech/feed",
        "tags_hint": ["storage", "sync-systems", "cloud-infrastructure"],
    },
]

# WHY A LIST OF DICTS instead of a class?
# For configuration data that you only READ (never mutate), plain dicts are simpler.
# A class would add overhead without benefit here.
# If you add runtime behavior (like "fetch this blog on a schedule"), THEN graduate to a class.

# INTERVIEW INSIGHT:
# This pattern — separate config from code — maps to what Netflix calls "externalized configuration."
# In production, this would be a YAML/JSON file or a config service, not Python.
# Starting with Python is fine for learning; just know the production evolution path.
