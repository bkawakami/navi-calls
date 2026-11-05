import os

os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27027")
os.environ.setdefault("MONGODB_DB_NAME", "navi_test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("RECALL_API_KEY", "test-recall-key")
os.environ.setdefault("RECALL_REALTIME_SECRET", "rt-secret")
os.environ.setdefault("BASE_URL", "https://navi.example.com")
