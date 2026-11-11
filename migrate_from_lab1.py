from common import mongo_db, pg_connect

QUERY = """
SELECT b.book_id, b.isbn, b.title, b.language, b.publish_year, b.pages, b.description,
       json_build_object('id', p.publisher_id, 'name', p.name, 'city', p.city) AS publisher,
       coalesce((SELECT json_agg(json_build_object('id', a.author_id, 'name', a.first_name || ' ' || a.last_name,
                                                   'country', a.country) ORDER BY ba.author_order)
                   FROM library.book_authors ba JOIN library.authors a ON a.author_id = ba.author_id
                  WHERE ba.book_id = b.book_id), '[]') AS authors,
       coalesce((SELECT json_agg(json_build_object('id', g.genre_id, 'name', g.name))
                   FROM library.book_genres bg JOIN library.genres g ON g.genre_id = bg.genre_id
                  WHERE bg.book_id = b.book_id), '[]') AS genres,
       coalesce((SELECT json_agg(json_build_object('copy_id', c.copy_id, 'inventory_code', c.inventory_code,
                                                   'branch', json_build_object('id', br.branch_id, 'name', br.name),
                                                   'status', c.status::text, 'shelf', c.shelf))
                   FROM library.book_copies c JOIN library.branches br ON br.branch_id = c.branch_id
                  WHERE c.book_id = b.book_id AND NOT c.is_deleted), '[]') AS copies,
       coalesce((SELECT json_agg(json_build_object('member', json_build_object('id', m.member_id,
                                                   'name', m.first_name || ' ' || m.last_name),
                                                   'rating', r.rating, 'comment', r.comment, 'created_at', r.created_at)
                                 ORDER BY r.created_at DESC)
                   FROM library.book_reviews r JOIN library.members m ON m.member_id = r.member_id
                  WHERE r.book_id = b.book_id AND NOT r.is_deleted), '[]') AS reviews
  FROM library.books b
  LEFT JOIN library.publishers p ON p.publisher_id = b.publisher_id
 WHERE NOT b.is_deleted
 ORDER BY b.book_id
"""


def main():
    pg = pg_connect()
    cur = pg.cursor()
    rows = cur.execute(QUERY).fetchall()
    names = [d.name for d in cur.description]
    docs = []
    for row in rows:
        r = dict(zip(names, row))
        ratings = [x["rating"] for x in r["reviews"]]
        docs.append({
            "_id": r["book_id"],
            "isbn": r["isbn"],
            "title": r["title"],
            "language": r["language"],
            "format": "print",
            "publish_year": r["publish_year"],
            "pages": r["pages"],
            "description": r["description"],
            "publisher": r["publisher"],
            "authors": r["authors"],
            "genres": r["genres"],
            "copies": r["copies"],
            "rating": {"sum": sum(ratings), "count": len(ratings), "avg": round(sum(ratings) / len(ratings), 3) if ratings else None},
            "recent_reviews": r["reviews"][:5],
        })
    db = mongo_db()
    db.lab1_catalog.drop()
    if docs:
        db.lab1_catalog.insert_many(docs)
    db.lab1_catalog.create_index("authors.id")
    db.lab1_catalog.create_index("genres.id")
    print(f"Перенесено {len(docs)} книг із бази лабораторної 1 у колекцію library_lab2.lab1_catalog")
    sample = db.lab1_catalog.find_one({}, {"title": 1, "authors.name": 1, "genres.name": 1, "copies": {"$slice": 1}, "rating": 1})
    print("Приклад документа:", sample)


if __name__ == "__main__":
    main()
