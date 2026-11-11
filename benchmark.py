import argparse
import csv
import json
import platform
import random
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from common import mongo_db, pg_connect
from generate import WORDS

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

SQL_BOOK_CARD = """
SELECT b.book_id, b.isbn, b.title, b.language, b.format, b.publish_year, b.pages, b.description,
       json_build_object('id', p.publisher_id, 'name', p.name, 'city', p.city) AS publisher,
       b.rating_sum, b.rating_count,
       (SELECT json_agg(json_build_object('id', a.author_id, 'name', a.first_name || ' ' || a.last_name, 'country', a.country)
                        ORDER BY ba.author_order)
          FROM book_authors ba JOIN authors a ON a.author_id = ba.author_id
         WHERE ba.book_id = b.book_id) AS authors,
       (SELECT json_agg(json_build_object('id', g.genre_id, 'name', g.name))
          FROM book_genres bg JOIN genres g ON g.genre_id = bg.genre_id
         WHERE bg.book_id = b.book_id) AS genres,
       (SELECT json_agg(t.tag) FROM book_tags t WHERE t.book_id = b.book_id) AS tags,
       (SELECT row_to_json(e) FROM ebook_details e WHERE e.book_id = b.book_id) AS ebook,
       (SELECT row_to_json(ad) FROM audiobook_details ad WHERE ad.book_id = b.book_id) AS audiobook,
       (SELECT json_agg(json_build_object('copy_id', c.copy_id, 'inventory_code', c.inventory_code,
                                          'branch', json_build_object('id', br.branch_id, 'name', br.name), 'status', c.status))
          FROM book_copies c JOIN branches br ON br.branch_id = c.branch_id
         WHERE c.book_id = b.book_id) AS copies,
       (SELECT json_agg(x) FROM (
            SELECT r.review_id, json_build_object('id', m.member_id, 'name', m.full_name) AS member,
                   r.rating, r.comment, r.created_at
              FROM reviews r JOIN members m ON m.member_id = r.member_id
             WHERE r.book_id = b.book_id
             ORDER BY r.created_at DESC
             LIMIT 5) x) AS recent_reviews
  FROM books b
  LEFT JOIN publishers p ON p.publisher_id = b.publisher_id
 WHERE b.book_id = %s
"""

SQL_FILTERED_SEARCH = """
SELECT x.book_id, x.title, x.avg_rating,
       (SELECT string_agg(a.first_name || ' ' || a.last_name, ', ' ORDER BY ba.author_order)
          FROM book_authors ba JOIN authors a ON a.author_id = ba.author_id
         WHERE ba.book_id = x.book_id) AS authors
  FROM (SELECT b.book_id, b.title, b.rating_sum::numeric / nullif(b.rating_count, 0) AS avg_rating
          FROM books b
          JOIN book_genres bg ON bg.book_id = b.book_id AND bg.genre_id = %(genre)s
         WHERE b.language = %(lang)s
           AND b.publish_year BETWEEN %(y1)s AND %(y2)s
           AND EXISTS (SELECT 1 FROM book_copies c
                        WHERE c.book_id = b.book_id AND c.branch_id = %(branch)s AND c.status = 'available')
         ORDER BY b.rating_sum::numeric / nullif(b.rating_count, 0) DESC NULLS LAST
         LIMIT 20) x
"""

JSONB_FILTERED_SEARCH = """
SELECT doc->>'title' AS title, doc->'authors' AS authors, doc->'rating'->>'avg' AS avg_rating
  FROM book_documents
 WHERE doc @> %(filter)s
   AND (doc->>'publish_year')::int BETWEEN %(y1)s AND %(y2)s
 ORDER BY (doc->'rating'->>'avg')::numeric DESC NULLS LAST
 LIMIT 20
"""

SQL_FTS = """
SELECT book_id, title
  FROM books
 WHERE to_tsvector('simple', title || ' ' || coalesce(description, '')) @@ plainto_tsquery('simple', %s)
 LIMIT 20
"""

SQL_GENRE_STATS = """
SELECT g.name, count(*) AS books, round(avg(b.rating_sum::numeric / nullif(b.rating_count, 0)), 3) AS avg_rating
  FROM genres g
  JOIN book_genres bg ON bg.genre_id = g.genre_id
  JOIN books b ON b.book_id = bg.book_id
 GROUP BY g.name
 ORDER BY books DESC
"""

SQL_MEMBER_EVENTS = """
SELECT event_id, event_type, ts, book_id, branch_id, query_text, results_count, device, duration_sec
  FROM reader_events
 WHERE member_id = %s
 ORDER BY ts DESC
 LIMIT 20
"""

SQL_EVENT_STATS = """
SELECT event_type, count(*) AS events, count(DISTINCT member_id) AS members
  FROM reader_events
 WHERE ts >= %s AND ts < %s
 GROUP BY event_type
"""


class Bench:
    def __init__(self, iterations, warmup, seed):
        self.iterations = iterations
        self.warmup = warmup
        self.rng = random.Random(seed)
        self.pg = pg_connect(autocommit=True)
        self.db = mongo_db()
        self.results = []
        self.notes = {}
        self.cleanup()
        self.load_context()

    def cleanup(self):
        cur = self.pg.cursor()
        cur.execute("DELETE FROM books WHERE book_id >= 10000000")
        cur.execute("DELETE FROM book_documents WHERE book_id >= 10000000")
        cur.execute("DELETE FROM reviews WHERE review_id >= 900000000")
        cur.execute("DELETE FROM reader_events WHERE event_id >= 500000000")
        cur.execute("VACUUM ANALYZE")
        self.db.books.delete_many({"_id": {"$gte": 10_000_000}})
        self.db.reviews.delete_many({"_id": {"$gte": 900_000_000}})
        self.db.events.delete_many({"_id": {"$gte": 500_000_000}})

    def load_context(self):
        cur = self.pg.cursor()
        self.max_book = cur.execute("SELECT max(book_id) FROM books WHERE book_id < 10000000").fetchone()[0]
        self.n_members = cur.execute("SELECT count(*) FROM members").fetchone()[0]
        self.genre_ids = [r[0] for r in cur.execute("SELECT genre_id FROM genres")]
        self.genre_names = dict(cur.execute("SELECT genre_id, name FROM genres").fetchall())
        self.branch_names = dict(cur.execute("SELECT branch_id, name FROM branches").fetchall())
        self.authors = {r[0]: (r[1], r[2], r[3]) for r in cur.execute("SELECT author_id, first_name, last_name, country FROM authors")}
        self.member_names = None
        self.prolific = cur.execute("""
            SELECT author_id, count(*) FROM book_authors GROUP BY author_id ORDER BY count(*) DESC LIMIT 200
        """).fetchall()
        self.counts = {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in (
            "books", "authors", "members", "book_copies", "reviews", "reader_events")}

    def measure(self, scenario, engines, params, iterations=None, warmup=None):
        iterations = iterations or self.iterations
        warmup = self.warmup if warmup is None else warmup
        timings = {name: [] for name in engines}
        names = list(engines)
        for i in range(warmup + iterations):
            p = params(i)
            order = names[:]
            self.rng.shuffle(order)
            for name in order:
                t0 = time.perf_counter_ns()
                engines[name](p)
                elapsed = time.perf_counter_ns() - t0
                if i >= warmup:
                    timings[name].append(elapsed / 1e6)
        for name, values in timings.items():
            values.sort()
            row = {
                "scenario": scenario,
                "engine": name,
                "n": len(values),
                "mean_ms": statistics.fmean(values),
                "median_ms": statistics.median(values),
                "p95_ms": values[int(0.95 * (len(values) - 1))],
                "min_ms": values[0],
            }
            row["ops_per_sec"] = 1000.0 / row["mean_ms"]
            self.results.append(row)
            print(f"  {name:<20} median {row['median_ms']:9.3f} ms   p95 {row['p95_ms']:9.3f} ms   {row['ops_per_sec']:9.1f} оп/с")

    def random_book(self, _):
        return self.rng.randint(1, self.max_book)

    def r1_book_card(self):
        print("R1. Картка книги за id")
        cur = self.pg.cursor()
        engines = {
            "PostgreSQL": lambda bid: cur.execute(SQL_BOOK_CARD, (bid,)).fetchone(),
            "PostgreSQL JSONB": lambda bid: cur.execute("SELECT doc FROM book_documents WHERE book_id = %s", (bid,)).fetchone(),
            "MongoDB": lambda bid: self.db.books.find_one({"_id": bid}),
        }
        self.measure("R1 Картка книги (1 документ ↔ 12 таблиць)", engines, self.random_book)

    def r2_filtered_search(self):
        print("R2. Пошук у каталозі з фільтрами")
        cur = self.pg.cursor()

        def params(_):
            y1 = self.rng.randint(1950, 2015)
            return {"genre": self.rng.choice(self.genre_ids), "lang": "uk", "y1": y1, "y2": y1 + 10,
                    "branch": self.rng.choice(list(self.branch_names))}

        def mongo(p):
            return list(self.db.books.find(
                {"genres.id": p["genre"], "language": p["lang"], "publish_year": {"$gte": p["y1"], "$lte": p["y2"]},
                 "copies": {"$elemMatch": {"branch.id": p["branch"], "status": "available"}}},
                {"title": 1, "authors.name": 1, "rating.avg": 1},
            ).sort("rating.avg", -1).limit(20))

        def jsonb(p):
            flt = {"language": p["lang"], "genres": [{"id": p["genre"]}],
                   "copies": [{"branch": {"id": p["branch"]}, "status": "available"}]}
            return cur.execute(JSONB_FILTERED_SEARCH, {"filter": Jsonb(flt), "y1": p["y1"], "y2": p["y2"]}).fetchall()

        engines = {
            "PostgreSQL": lambda p: cur.execute(SQL_FILTERED_SEARCH, p).fetchall(),
            "PostgreSQL JSONB": jsonb,
            "MongoDB": mongo,
        }
        self.measure("R2 Пошук: жанр + мова + роки + є в філії, топ-20 за рейтингом", engines, params)

    def r3_fulltext(self):
        print("R3. Повнотекстовий пошук")
        cur = self.pg.cursor()
        engines = {
            "PostgreSQL": lambda w: cur.execute(SQL_FTS, (w,)).fetchall(),
            "MongoDB": lambda w: list(self.db.books.find({"$text": {"$search": w}}, {"title": 1}).limit(20)),
        }
        self.measure("R3 Повнотекстовий пошук за словом", engines, lambda _: self.rng.choice(WORDS))

    def r4_genre_stats(self):
        print("R4. Аналітика: кількість книг і рейтинг по жанрах")
        cur = self.pg.cursor()
        pipeline = [
            {"$unwind": "$genres"},
            {"$group": {"_id": "$genres.name", "books": {"$sum": 1}, "avg_rating": {"$avg": "$rating.avg"}}},
            {"$sort": {"books": -1}},
        ]
        engines = {
            "PostgreSQL": lambda _: cur.execute(SQL_GENRE_STATS).fetchall(),
            "MongoDB": lambda _: list(self.db.books.aggregate(pipeline)),
        }
        n = max(10, self.iterations // 20)
        self.measure("R4 Аналітика по всіх книгах (GROUP BY жанр)", engines, lambda _: None, iterations=n, warmup=2)

    def r5_member_events(self):
        print("R5. Останні 20 подій читача")
        cur = self.pg.cursor()
        engines = {
            "PostgreSQL": lambda m: cur.execute(SQL_MEMBER_EVENTS, (m,)).fetchall(),
            "MongoDB": lambda m: list(self.db.events.find({"member_id": m}).sort("ts", -1).limit(20)),
        }
        self.measure("R5 Останні 20 подій читача", engines, lambda _: self.rng.randint(1, self.n_members))

    def r6_event_stats(self):
        print("R6. Статистика подій за тиждень")
        cur = self.pg.cursor()

        def params(_):
            start = NOW - timedelta(days=self.rng.randint(7, 89))
            return start, start + timedelta(days=7)

        def mongo(p):
            return list(self.db.events.aggregate([
                {"$match": {"ts": {"$gte": p[0], "$lt": p[1]}}},
                {"$group": {"_id": {"t": "$type", "m": "$member_id"}, "n": {"$sum": 1}}},
                {"$group": {"_id": "$_id.t", "events": {"$sum": "$n"}, "members": {"$sum": 1}}},
            ]))

        engines = {
            "PostgreSQL": lambda p: cur.execute(SQL_EVENT_STATS, p).fetchall(),
            "MongoDB": mongo,
        }
        n = max(10, self.iterations // 20)
        self.measure("R6 Статистика подій за 7 днів (по типах)", engines, params, iterations=n, warmup=2)

    def w1_insert_book(self):
        print("W1. Додавання нової книги з авторами, жанрами, тегами і 3 примірниками")
        cur = self.pg.cursor()
        seq = iter(range(10_000_000, 20_000_000))
        copy_seq = iter(range(50_000_000, 90_000_000))
        author_ids = list(self.authors)

        def params(_):
            bid = next(seq)
            branches = list(self.branch_names)
            return {
                "book_id": bid,
                "isbn": f"979{bid:010d}",
                "title": f"Нова книга {bid}",
                "year": 2026,
                "authors": self.rng.sample(author_ids, 2),
                "genres": self.rng.sample(self.genre_ids, 2),
                "tags": ["новинка", "бестселер"],
                "copies": [(next(copy_seq), self.rng.choice(branches)) for _ in range(3)],
            }

        def to_doc(p):
            return {
                "_id": p["book_id"], "isbn": p["isbn"], "title": p["title"], "language": "uk", "format": "print",
                "publish_year": p["year"], "pages": 320, "description": "нова книга бібліотеки",
                "publisher": {"id": 1, "name": "Видавництво", "city": "Київ"},
                "authors": [{"id": a, "name": f"{self.authors[a][0]} {self.authors[a][1]}", "country": self.authors[a][2]} for a in p["authors"]],
                "genres": [{"id": g, "name": self.genre_names[g]} for g in p["genres"]],
                "tags": p["tags"],
                "copies": [{"copy_id": c, "inventory_code": f"NEW-{c}", "branch": {"id": b, "name": self.branch_names[b]}, "status": "available"}
                           for c, b in p["copies"]],
                "rating": {"sum": 0, "count": 0, "avg": None},
                "recent_reviews": [],
                "created_at": NOW,
            }

        def sql(p):
            with self.pg.transaction():
                cur.execute("""INSERT INTO books (book_id, isbn, title, publisher_id, publish_year, language, format, pages, description)
                               VALUES (%s, %s, %s, 1, %s, 'uk', 'print', 320, 'нова книга бібліотеки')""",
                            (p["book_id"], p["isbn"], p["title"], p["year"]))
                cur.executemany("INSERT INTO book_authors VALUES (%s, %s, %s)", [(p["book_id"], a, i + 1) for i, a in enumerate(p["authors"])])
                cur.executemany("INSERT INTO book_genres VALUES (%s, %s)", [(p["book_id"], g) for g in p["genres"]])
                cur.executemany("INSERT INTO book_tags VALUES (%s, %s)", [(p["book_id"], t) for t in p["tags"]])
                cur.executemany("INSERT INTO book_copies VALUES (%s, %s, %s, %s, 'available')",
                                [(c, p["book_id"], b, f"NEW-{c}") for c, b in p["copies"]])

        def jsonb(p):
            cur.execute("INSERT INTO book_documents VALUES (%s, %s)", (p["book_id"] + 5_000_000, Jsonb(json.loads(json.dumps(to_doc(p), default=str)))))

        engines = {
            "PostgreSQL": sql,
            "PostgreSQL JSONB": jsonb,
            "MongoDB": lambda p: self.db.books.insert_one(to_doc(p)),
        }
        self.measure("W1 Нова книга (1 insert ↔ 5 таблиць у транзакції)", engines, params)

    def w2_add_review(self):
        print("W2. Новий відгук з перерахунком рейтингу книги")
        cur = self.pg.cursor()
        seq = iter(range(900_000_000, 999_999_999))

        def params(_):
            return {"review_id": next(seq), "book_id": self.random_book(None), "member_id": self.rng.randint(1, self.n_members),
                    "rating": self.rng.randint(1, 5), "comment": "Дуже сподобалась книга"}

        def sql(p):
            with self.pg.transaction():
                cur.execute("INSERT INTO reviews VALUES (%(review_id)s, %(book_id)s, %(member_id)s, %(rating)s, %(comment)s, now())", p)
                cur.execute("UPDATE books SET rating_sum = rating_sum + %(rating)s, rating_count = rating_count + 1 WHERE book_id = %(book_id)s", p)

        def mongo(p):
            review = {"_id": p["review_id"], "book_id": p["book_id"], "member": {"id": p["member_id"], "name": "Читач"},
                      "rating": p["rating"], "comment": p["comment"], "created_at": datetime.now(timezone.utc)}
            self.db.reviews.insert_one(review)
            short = {k: review[k] for k in ("member", "rating", "comment", "created_at")}
            short["review_id"] = review["_id"]
            self.db.books.update_one({"_id": p["book_id"]}, [
                {"$set": {"rating.sum": {"$add": ["$rating.sum", p["rating"]]}, "rating.count": {"$add": ["$rating.count", 1]}}},
                {"$set": {"rating.avg": {"$round": [{"$divide": ["$rating.sum", "$rating.count"]}, 3]},
                          "recent_reviews": {"$slice": [{"$concatArrays": [[short], "$recent_reviews"]}, 5]}}},
            ])

        self.measure("W2 Новий відгук + оновлення рейтингу", {"PostgreSQL": sql, "MongoDB": mongo}, params)

    def w3_rename_author(self):
        print("W3. Зміна імені автора (дані, продубльовані в багатьох документах)")
        cur = self.pg.cursor()
        authors = [a for a, _ in self.prolific]
        books_per_author = statistics.fmean(c for _, c in self.prolific)
        self.notes["W3"] = f"у середньому {books_per_author:.1f} книг на автора з вибірки (200 найпродуктивніших авторів)"
        counter = iter(range(1, 10**9))

        def params(_):
            a = self.rng.choice(authors)
            return {"author_id": a, "suffix": next(counter)}

        def sql(p):
            cur.execute("UPDATE authors SET last_name = %s WHERE author_id = %s",
                        (f"{self.authors[p['author_id']][1]}-{p['suffix']}", p["author_id"]))

        def mongo(p):
            new_name = f"{self.authors[p['author_id']][0]} {self.authors[p['author_id']][1]}-{p['suffix']}"
            self.db.books.update_many({"authors.id": p["author_id"]}, {"$set": {"authors.$[a].name": new_name}},
                                      array_filters=[{"a.id": p["author_id"]}])

        n = max(50, self.iterations // 3)
        self.measure("W3 Перейменування автора (1 рядок ↔ N документів)", {"PostgreSQL": sql, "MongoDB": mongo}, params, iterations=n, warmup=5)

    def w4_bulk_events(self):
        print("W4. Пакетний запис 10 000 подій")
        cur = self.pg.cursor()
        seq = iter(range(500_000_000, 900_000_000))
        size = 10_000

        def params(_):
            rows = []
            for _ in range(size):
                rows.append({"_id": next(seq), "member_id": self.rng.randint(1, self.n_members), "type": "view",
                             "ts": NOW, "book_id": self.random_book(None), "device": "web", "duration_sec": self.rng.randint(3, 600)})
            return rows

        def sql_insert(rows):
            with self.pg.transaction():
                cur.executemany("""INSERT INTO reader_events (event_id, member_id, event_type, ts, book_id, device, duration_sec)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                                [(r["_id"] + 100_000_000, r["member_id"], r["type"], r["ts"], r["book_id"], r["device"], r["duration_sec"]) for r in rows])

        def sql_copy(rows):
            with self.pg.transaction():
                with cur.copy("COPY reader_events (event_id, member_id, event_type, ts, book_id, device, duration_sec) FROM STDIN") as cp:
                    for r in rows:
                        cp.write_row((r["_id"] + 200_000_000, r["member_id"], r["type"], r["ts"], r["book_id"], r["device"], r["duration_sec"]))

        def mongo(rows):
            self.db.events.insert_many([dict(r) for r in rows], ordered=False)

        engines = {"PostgreSQL INSERT": sql_insert, "PostgreSQL COPY": sql_copy, "MongoDB": mongo}
        self.measure("W4 Пакетний запис 10 000 подій", engines, params, iterations=10, warmup=1)

    def w5_issue_copy(self):
        print("W5. Видача примірника (зміна статусу)")
        cur = self.pg.cursor()
        total = self.warmup + self.iterations
        copies = [r[0] for r in cur.execute(
            "SELECT copy_id FROM book_copies WHERE status = 'available' AND copy_id < 50000000 ORDER BY random() LIMIT %s", (total,))]
        it = iter(copies)

        def sql(cid):
            cur.execute("UPDATE book_copies SET status = 'on_loan' WHERE copy_id = %s AND status = 'available'", (cid,))

        def mongo(cid):
            self.db.books.update_one({"copies.copy_id": cid}, {"$set": {"copies.$[c].status": "on_loan"}}, array_filters=[{"c.copy_id": cid}])

        self.measure("W5 Видача примірника (статус у вкладеному масиві)", {"PostgreSQL": sql, "MongoDB": mongo}, lambda _: next(it),
                     iterations=len(copies) - self.warmup)

    def storage(self):
        cur = self.pg.cursor()
        sizes = dict(cur.execute("""
            SELECT c.relname, pg_total_relation_size(c.oid)
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'lab2' AND c.relkind = 'r'
        """).fetchall())
        catalog_tables = ["books", "publishers", "authors", "genres", "book_authors", "book_genres", "book_tags",
                          "ebook_details", "audiobook_details", "book_copies", "branches", "reviews", "members"]
        mb = 1024 * 1024
        rows = [
            ("PostgreSQL: каталог (13 таблиць + індекси)", sum(sizes[t] for t in catalog_tables) / mb),
            ("PostgreSQL JSONB: book_documents + індекс", sizes["book_documents"] / mb),
            ("PostgreSQL: reader_events + індекси", sizes["reader_events"] / mb),
        ]
        for coll in ("books", "reviews", "events"):
            st = self.db.command("collStats", coll)
            rows.append((f"MongoDB: {coll} (на диску, зі стисненням + індекси)", (st["storageSize"] + st["totalIndexSize"]) / mb))
        return rows

    def explain(self):
        cur = self.pg.cursor()
        p = {"genre": self.genre_ids[0], "lang": "uk", "y1": 1990, "y2": 2000, "branch": 1}
        lines = ["PostgreSQL, R2:", ""]
        lines += [r[0] for r in cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + SQL_FILTERED_SEARCH, p)]
        lines += ["", "PostgreSQL, R5:", ""]
        lines += [r[0] for r in cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + SQL_MEMBER_EVENTS, (1,))]
        plan = self.db.books.find(
            {"genres.id": p["genre"], "language": "uk", "publish_year": {"$gte": 1990, "$lte": 2000},
             "copies": {"$elemMatch": {"branch.id": 1, "status": "available"}}}
        ).sort("rating.avg", -1).limit(20).explain()
        win = plan["queryPlanner"]["winningPlan"]
        stats = plan.get("executionStats", {})
        lines += ["", "MongoDB, R2 (winningPlan):", "", json.dumps(win, ensure_ascii=False, indent=2, default=str)]
        if stats:
            lines += ["", f"totalDocsExamined={stats.get('totalDocsExamined')}, totalKeysExamined={stats.get('totalKeysExamined')}, nReturned={stats.get('nReturned')}"]
        return "\n".join(lines)

    def save(self):
        RESULTS.mkdir(exist_ok=True)
        tag = f"{self.counts['books'] // 1000}k"
        with open(RESULTS / f"benchmark_{tag}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(self.results[0]))
            w.writeheader()
            w.writerows(self.results)

        storage = self.storage()
        md = [f"# Результати тестування швидкодії ({self.counts['books']:,} книг)".replace(",", " "), ""]
        md.append(f"Дата: {datetime.now():%d.%m.%Y %H:%M}, ОС: {platform.system()} {platform.machine()}, Python {platform.python_version()}")
        md.append("")
        md.append("Обсяг даних: " + ", ".join(f"{k} = {v:,}".replace(",", " ") for k, v in self.counts.items()))
        md.append("")
        md.append("| Сценарій | СУБД | n | Медіана, мс | p95, мс | Мін, мс | Оп/с |")
        md.append("|---|---|---:|---:|---:|---:|---:|")
        for r in self.results:
            md.append(f"| {r['scenario']} | {r['engine']} | {r['n']} | {r['median_ms']:.3f} | {r['p95_ms']:.3f} | {r['min_ms']:.3f} | {r['ops_per_sec']:.1f} |")
        md.append("")
        for k, v in self.notes.items():
            md.append(f"- {k}: {v}")
        md.append("")
        md.append("## Обсяг на диску")
        md.append("")
        md.append("| Об'єкт | МБ |")
        md.append("|---|---:|")
        for name, size in storage:
            md.append(f"| {name} | {size:.1f} |")
        (RESULTS / f"benchmark_{tag}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        (RESULTS / f"plans_{tag}.txt").write_text(self.explain(), encoding="utf-8")
        self.chart(tag)
        print(f"\nРезультати збережено в results/benchmark_{tag}.md, .csv, .png і results/plans_{tag}.txt")

    def chart(self, tag):
        plot(self.results, self.counts["books"], RESULTS / f"benchmark_{tag}.png")


SHORT = {
    "R1": "R1 Картка книги", "R2": "R2 Пошук з фільтрами", "R3": "R3 Повнотекстовий пошук",
    "R4": "R4 Аналітика по жанрах", "R5": "R5 Останні події читача", "R6": "R6 Статистика подій",
    "W1": "W1 Нова книга", "W2": "W2 Новий відгук", "W3": "W3 Перейменування автора",
    "W4": "W4 10 000 подій пакетом", "W5": "W5 Видача примірника",
}
COLORS = {"PostgreSQL": "#336791", "PostgreSQL JSONB": "#8DB3D9", "MongoDB": "#47A248",
          "PostgreSQL INSERT": "#336791", "PostgreSQL COPY": "#173550"}


def plot(results, books, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scenarios = list(dict.fromkeys(r["scenario"] for r in results))
    fig, ax = plt.subplots(figsize=(11, 0.95 * len(scenarios) + 1.5))
    yticks, ylabels, seen = [], [], set()
    y = 0.0
    for sc in scenarios:
        rows = [r for r in results if r["scenario"] == sc]
        h = 0.8 / len(rows)
        top = y
        for r in rows:
            value = float(r["median_ms"])
            label = r["engine"] if r["engine"] not in seen else None
            seen.add(r["engine"])
            ax.barh(y, value, height=h * 0.92, color=COLORS.get(r["engine"], "#999999"), label=label)
            ax.text(value * 1.06, y, f"{value:.2f}", va="center", fontsize=8)
            y += h
        yticks.append((top + y - h) / 2)
        ylabels.append(SHORT.get(sc.split(" ")[0], sc))
        y += 0.45
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlim(right=ax.get_xlim()[1] * 3)
    ax.set_xlabel("Медіанний час, мс (логарифмічна шкала, менше = краще)")
    ax.set_title(f"PostgreSQL vs MongoDB: {books:,} книг".replace(",", " "))
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Порівняння швидкодії PostgreSQL і MongoDB")
    parser.add_argument("--iterations", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    bench = Bench(args.iterations, args.warmup, args.seed)
    print("Обсяг даних:", ", ".join(f"{k}={v}" for k, v in bench.counts.items()))
    for step in (bench.r1_book_card, bench.r2_filtered_search, bench.r3_fulltext, bench.r4_genre_stats,
                 bench.r5_member_events, bench.r6_event_stats, bench.w1_insert_book, bench.w2_add_review,
                 bench.w3_rename_author, bench.w4_bulk_events, bench.w5_issue_copy):
        step()
    bench.save()


if __name__ == "__main__":
    main()
