"""MongoDB collection schema (validation) and Python model for news articles.

This module provides:
- a JSON Schema validator suitable for MongoDB collection validation
- a small helper to apply the validator and create useful indexes
- a Pydantic `ArticleModel` for Python-side validation/typing

Fields derived from the codebase (`app/rss_parser.py` and `app/mongo.py`):
- `title` (string) - article headline
- `link` (string) - URL to original article (sometimes called `url` in code)
- `summary` (string) - short summary or description
- `published` (date) - publication datetime (stored as BSON Date)
- optional: `source`, `guid`, `created_at`, `updated_at`

Usage (example):
	from pymongo import MongoClient
	from app.schema.shcema import apply_articles_validator

	client = MongoClient(MONGODB_URL)
	db = client.get_database('news')
	apply_articles_validator(db)

"""

from typing import Optional
import re
from datetime import datetime

from pydantic import BaseModel, AnyUrl, Field

from pymongo.database import Database


# JSON Schema for MongoDB collection validation
ARTICLES_JSON_SCHEMA = {
	"$jsonSchema": {
		"bsonType": "object",
		"required": ["title", "link", "published"],
		"properties": {
			"title": {"bsonType": "string", "description": "Article title"},
			"url": {"bsonType": "string", "description": "Canonical URL to the article"},
			"summary": {"bsonType": "string", "description": "Short description or summary"},
			"published": {"bsonType": "date", "description": "Publication datetime"},
			"created_at": {"bsonType": "date", "description": "When the document was created in the DB"},
			"is_sent": {"bsonType": "bool", "description": "Whether the article has been sent to Telegram"}
		}
	}
}


def apply_articles_validator(db: Database, collection_name: str = "articles") -> None:
	"""Apply the JSON Schema validator to the `articles` collection and create useful indexes.

	This will create the collection if it doesn't exist, or update its validator via `collMod`.
	It also ensures a unique index on `link` to avoid duplicate saves of the same article.
	"""
	# Create collection if missing
	if collection_name not in db.list_collection_names():
		db.create_collection(collection_name)

	# Apply/modify validator
	try:
		db.command(
			"collMod",
			collection_name,
			validator=ARTICLES_JSON_SCHEMA,
			validationLevel="moderate",
		)
	except Exception:
		# If collMod fails (older server versions), try creating with validator
		db.drop_collection(collection_name)
		db.create_collection(collection_name, validator=ARTICLES_JSON_SCHEMA, validationLevel="moderate")

	# Create unique index on link (if present) and index on published
	coll = db.get_collection(collection_name)
	coll.create_index([("link", 1)], unique=True, name="idx_unique_link")
	coll.create_index([("published", -1)], name="idx_published_desc")


class ArticleModel(BaseModel):
	"""Pydantic model for articles used in the application.

	This helps validate articles before inserting into MongoDB and provides typing.
	"""

	title: str = Field(..., description="Article title")
	link: AnyUrl = Field(..., description="Canonical URL to the article")
	summary: Optional[str] = Field(None, description="Short description or summary")
	published: datetime = Field(..., description="Publication datetime (aware or naive)")
	source: Optional[str] = None
	guid: Optional[str] = None
	created_at: Optional[datetime] = None
	updated_at: Optional[datetime] = None

	class Config:
		orm_mode = True


def normalize_article_dict(d: dict) -> dict:
	"""Normalize incoming article dicts from RSS parsing to canonical keys.

	- Accepts `url` or `link` and normalizes to `link`.
	- Ensures `published` is a datetime.
	- Adds `created_at` timestamp if missing.
	"""
	out = dict(d)
	# accept 'url' as alias for 'link'
	if "url" in out and "link" not in out:
		out["link"] = out.pop("url")

	# If published is a struct_time or tuple, the app should convert earlier; here we assume datetime
	if "published" in out and not isinstance(out["published"], datetime):
		# best-effort: if it's a tuple like (Y,M,D,h,m,s,...) convert
		try:
			out["published"] = datetime(*out["published"][:6])
		except Exception:
			out["published"] = None

	if "created_at" not in out or out.get("created_at") is None:
		out["created_at"] = datetime.utcnow()

	return out

