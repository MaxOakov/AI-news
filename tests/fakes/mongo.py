"""A minimal in-memory stand-in for pymongo, used to test the app/db
repositories without a real MongoDB connection.

One generic FakeCollection implements every operation the repositories
actually issue (plain equality filters, the `$or`/`$exists`/`$gte` query
used by ArticleRepository.get_next_unsent, `$set`/`$setOnInsert` updates
with `upsert=True`, `sort=[(field, direction)]`, and `create_index`) rather
than four near-identical subclasses, since the real collections differ only
in which documents they hold, not in behavior.
"""
from datetime import datetime, timezone
from types import SimpleNamespace


def _matches(doc: dict, query: dict) -> bool:
    for key, value in query.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in value):
                return False
            continue
        if isinstance(value, dict) and "$exists" in value:
            if (key in doc) != value["$exists"]:
                return False
            continue
        if isinstance(value, dict) and "$gte" in value:
            # Like MongoDB, a missing/null field never satisfies a range query.
            if doc.get(key) is None or doc[key] < value["$gte"]:
                return False
            continue
        if doc.get(key) != value:
            return False
    return True


class FakeCollection:
    """In-memory stand-in for a single pymongo Collection."""

    def __init__(self):
        self.docs: list[dict] = []
        self.indexes: list[list[tuple]] = []
        self._next_id = 1

    def create_index(self, keys, **kwargs):
        """Record the index; like MongoDB, creating an existing one is a no-op."""
        if keys not in self.indexes:
            self.indexes.append(keys)
        return "_".join(f"{field}_{direction}" for field, direction in keys)

    def _fresh_id(self) -> str:
        fake_id = f"fake-id-{self._next_id}"
        self._next_id += 1
        return fake_id

    def _find_all(self, query: dict | None = None) -> list[dict]:
        query = query or {}
        return [d for d in self.docs if _matches(d, query)]

    def find(self, query: dict | None = None):
        return list(self._find_all(query))

    def find_one(self, query: dict | None = None, sort=None):
        matches = self._find_all(query)
        if sort:
            field, direction = sort[0]
            matches = sorted(
                matches,
                key=lambda d: d.get(field) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=(direction == -1),
            )
        return matches[0] if matches else None

    def count_documents(self, query: dict | None = None, limit=None):
        count = len(self._find_all(query))
        if limit is not None:
            count = min(count, limit)
        return count

    def insert_one(self, doc: dict):
        doc = dict(doc)
        doc.setdefault("_id", self._fresh_id())
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def update_one(self, filter: dict, update: dict, upsert: bool = False):
        matches = self._find_all(filter)
        if matches:
            matches[0].update(update.get("$set", {}))
            return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

        new_doc = dict(update.get("$set", {}))
        new_doc.update(update.get("$setOnInsert", {}))
        for key, value in filter.items():
            new_doc.setdefault(key, value)
        new_doc.setdefault("_id", self._fresh_id())
        self.docs.append(new_doc)
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=new_doc["_id"])

    def delete_one(self, filter: dict):
        matches = self._find_all(filter)
        if matches:
            self.docs.remove(matches[0])
            return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)
