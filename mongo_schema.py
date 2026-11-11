from pymongo import ASCENDING, DESCENDING, TEXT

BOOK_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "isbn", "title", "language", "format", "authors", "genres", "rating"],
        "properties": {
            "_id": {"bsonType": "int"},
            "isbn": {"bsonType": "string", "maxLength": 17},
            "title": {"bsonType": "string", "maxLength": 255},
            "language": {"bsonType": "string"},
            "format": {"enum": ["print", "ebook", "audiobook"]},
            "publish_year": {"bsonType": ["int", "null"]},
            "authors": {
                "bsonType": "array",
                "minItems": 1,
                "items": {
                    "bsonType": "object",
                    "required": ["id", "name"],
                    "properties": {"id": {"bsonType": "int"}, "name": {"bsonType": "string"}},
                },
            },
            "genres": {"bsonType": "array"},
            "copies": {"bsonType": "array"},
            "rating": {
                "bsonType": "object",
                "required": ["sum", "count", "avg"],
                "properties": {
                    "sum": {"bsonType": "int"},
                    "count": {"bsonType": "int"},
                    "avg": {"bsonType": ["double", "int", "null"]},
                },
            },
            "recent_reviews": {"bsonType": "array", "maxItems": 5},
        },
    }
}

REVIEW_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "book_id", "member", "rating", "created_at"],
        "properties": {
            "rating": {"bsonType": "int", "minimum": 1, "maximum": 5},
            "created_at": {"bsonType": "date"},
        },
    }
}

EVENT_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["_id", "member_id", "type", "ts"],
        "properties": {
            "type": {"enum": ["search", "view", "reserve", "download"]},
            "ts": {"bsonType": "date"},
        },
    }
}


def recreate_collections(db):
    for name in ("books", "reviews", "events"):
        db.drop_collection(name)
    db.create_collection("books", validator=BOOK_VALIDATOR)
    db.create_collection("reviews", validator=REVIEW_VALIDATOR)
    db.create_collection("events", validator=EVENT_VALIDATOR)


def create_indexes(db):
    db.books.create_index([("isbn", ASCENDING)], unique=True, name="ux_isbn")
    db.books.create_index(
        [("genres.id", ASCENDING), ("language", ASCENDING), ("publish_year", ASCENDING)],
        name="ix_genre_language_year",
    )
    db.books.create_index([("rating.avg", DESCENDING)], name="ix_rating")
    db.books.create_index([("authors.id", ASCENDING)], name="ix_authors")
    db.books.create_index([("tags", ASCENDING)], name="ix_tags")
    db.books.create_index([("copies.branch.id", ASCENDING), ("copies.status", ASCENDING)], name="ix_copies_branch_status")
    db.books.create_index([("copies.copy_id", ASCENDING)], name="ix_copies_id")
    db.books.create_index(
        [("title", TEXT), ("description", TEXT)],
        default_language="none",
        language_override="text_language",
        name="ix_fts",
    )
    db.reviews.create_index([("book_id", ASCENDING), ("created_at", DESCENDING)], name="ix_book_created")
    db.events.create_index([("member_id", ASCENDING), ("ts", DESCENDING)], name="ix_member_ts")
    db.events.create_index([("type", ASCENDING), ("ts", DESCENDING)], name="ix_type_ts")
    db.events.create_index([("ts", ASCENDING)], name="ix_ts")
