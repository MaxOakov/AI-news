from pymongo import MongoClient


class Database:
    """Owns the MongoDB connection lifecycle.

    Replaces the two module-level globals (`client`, `test_db`) that used to
    live in mongo.py. Connecting is still lazy (nothing happens until a
    collection is first accessed), but the connection is now instance state
    instead of shared module state, so nothing prevents constructing more
    than one Database (e.g. pointed at different URLs) if that's ever
    needed, and there's no hidden global anyone else could mutate.
    """

    def __init__(self, url: str | None):
        self._url = url
        self._client: MongoClient | None = None
        self._db = None

    def get_db(self):
        """Return the cached database handle, connecting on first use."""
        if self._db is not None:
            return self._db

        if not self._url:
            raise RuntimeError("MONGODB_URL is not configured.")

        self._client = MongoClient(self._url, serverSelectionTimeoutMS=5000)
        try:
            self._client.admin.command("ping")
            self._db = self._client["news"]
            print("Pinged your deployment. You successfully connected to MongoDB!")
            return self._db
        except Exception as exc:
            raise RuntimeError(f"MongoDB connection failed: {exc}") from exc

    @property
    def articles(self):
        return self.get_db().articles

    @property
    def chats(self):
        return self.get_db().chats

    @property
    def rss_links(self):
        return self.get_db().rss_links

    @property
    def chat_prompts(self):
        return self.get_db().chat_prompts
