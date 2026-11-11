import argparse
import itertools
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import mongo_db, pg_connect
from mongo_schema import create_indexes, recreate_collections

ROOT = Path(__file__).parent

FIRST_NAMES = [
    "Олександр", "Андрій", "Тарас", "Іван", "Михайло", "Дмитро", "Богдан", "Василь", "Петро", "Юрій",
    "Ольга", "Олена", "Марія", "Ірина", "Наталія", "Софія", "Анна", "Катерина", "Леся", "Ганна",
    "John", "Emily", "George", "Anna", "Mark", "Laura", "Adam", "Eva", "Tomasz", "Agnieszka",
]
LAST_NAMES = [
    "Шевченко", "Коваленко", "Бондаренко", "Ткаченко", "Кравченко", "Олійник", "Шевчук", "Поліщук",
    "Мельник", "Бойко", "Лисенко", "Руденко", "Савченко", "Петренко", "Марченко", "Гнатюк", "Мороз",
    "Литвиненко", "Карпенко", "Ярошенко", "Smith", "Brown", "Taylor", "Wilson", "Nowak", "Kowalski",
    "Wiśniewski", "Miller", "Davis", "Clark",
]
COUNTRIES = ["Україна", "Польща", "Велика Британія", "США", "Німеччина", "Франція", "Канада"]
CITIES = ["Київ", "Львів", "Харків", "Одеса", "Дніпро", "Вінниця", "Чернівці", "Полтава", "Ужгород", "Луцьк"]
GENRES = [
    "Роман", "Повість", "Поезія", "Драма", "Фентезі", "Наукова фантастика", "Детектив", "Трилер",
    "Історичний роман", "Біографія", "Мемуари", "Психологія", "Філософія", "Історія", "Економіка",
    "Програмування", "Бази даних", "Математика", "Фізика", "Біологія", "Медицина", "Право", "Мистецтво",
    "Кулінарія", "Подорожі", "Дитяча література", "Підліткова література", "Комікси", "Саморозвиток",
    "Бізнес", "Маркетинг", "Політологія", "Соціологія", "Мовознавство", "Педагогіка", "Релігієзнавство",
    "Архітектура", "Музика", "Спорт", "Гумор",
]
TAGS = [
    "бестселер", "новинка", "класика", "екранізація", "нагорода", "для_студентів", "переклад",
    "серія", "ілюстроване", "подарункове", "шкільна_програма", "рекомендує_бібліотекар", "короткий_список",
    "автограф", "рідкісне", "перевидання", "аудіо_версія", "велике_видання", "кишеньковий_формат",
    "україніка", "наукпоп", "для_дітей", "18+", "локальний_автор", "твердий_переплет", "м'який_переплет",
    "антологія", "біографічне", "документальне", "збірка",
]
TITLE_ADJ = [
    "Тихий", "Останній", "Забутий", "Новий", "Темний", "Зимовий", "Великий", "Чужий", "Золотий",
    "Перший", "Далекий", "Північний", "Silent", "Last", "Hidden", "Broken", "Lost", "Ancient",
]
TITLE_NOUN = [
    "сад", "вокзал", "берег", "острів", "архів", "лабіринт", "маяк", "світ", "код", "алгоритм",
    "мур", "ліс", "степ", "місто", "дім", "шлях", "garden", "harbor", "kingdom", "signal", "river", "empire",
]
WORDS = [
    "історія", "кохання", "війна", "пам'ять", "родина", "місто", "подорож", "таємниця", "свобода",
    "дружба", "наука", "мистецтво", "дані", "технології", "майбутнє", "минуле", "надія", "вибір",
    "зрада", "відвага", "мова", "культура", "дослідження", "експедиція", "детектив", "розслідування",
    "programming", "database", "design", "patterns", "history", "travel", "mystery", "science",
    "university", "student", "library", "reader", "book", "music", "economy", "philosophy",
]
NARRATORS = ["Остап Ступка", "Наталка Сумська", "Олексій Горбунов", "Ірма Вітовська", "Римма Зюбіна", "John Lee", "Kate Reading"]
DEVICES = ["web", "android", "ios", "kiosk"]
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def zipf_cum_weights(n, s=0.9):
    weights = [1.0 / (i + 1) ** s for i in range(n)]
    return list(itertools.accumulate(weights))


class Generator:
    def __init__(self, books, seed):
        self.rng = random.Random(seed)
        self.n_books = books
        self.n_authors = max(200, books // 5)
        self.n_members = max(1000, books // 2)
        self.n_publishers = 300
        self.branches = [(i + 1, f"Філія №{i + 1} ({CITIES[i]})", CITIES[i]) for i in range(10)]
        self.publishers = [
            (i + 1, f"Видавництво {self.rng.choice(LAST_NAMES)}-{i + 1}", self.rng.choice(CITIES))
            for i in range(self.n_publishers)
        ]
        self.genres = [(i + 1, g) for i, g in enumerate(GENRES)]
        self.authors = [
            (i + 1, self.rng.choice(FIRST_NAMES), self.rng.choice(LAST_NAMES), self.rng.choice(COUNTRIES))
            for i in range(self.n_authors)
        ]
        self.members = [
            (i + 1, f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}", f"reader{i + 1}@mail.ua")
            for i in range(self.n_members)
        ]
        self.author_ids = list(range(1, self.n_authors + 1))
        self.author_cw = zipf_cum_weights(self.n_authors)
        self.book_ids = list(range(1, self.n_books + 1))
        self.book_cw = zipf_cum_weights(self.n_books, 0.7)
        self.rng.shuffle(self.book_ids)
        self.copy_seq = itertools.count(1)
        self.review_seq = itertools.count(1)
        self.event_seq = itertools.count(1)

    def random_date(self, days_back):
        return NOW - timedelta(seconds=self.rng.randint(0, days_back * 86400))

    def text(self, a, b):
        return " ".join(self.rng.choice(WORDS) for _ in range(self.rng.randint(a, b)))

    def make_book(self, book_id):
        rng = self.rng
        fmt = rng.choices(["print", "ebook", "audiobook"], [0.7, 0.2, 0.1])[0]
        language = rng.choices(["uk", "en", "pl"], [0.6, 0.3, 0.1])[0]
        title = f"{rng.choice(TITLE_ADJ)} {rng.choice(TITLE_NOUN)} {rng.choice(WORDS)}"
        year = rng.randint(1950, 2025)
        pages = rng.randint(80, 900)
        description = self.text(12, 25)
        publisher = self.publishers[rng.randrange(self.n_publishers)]
        n_auth = rng.choices([1, 2, 3], [0.75, 0.2, 0.05])[0]
        author_ids = []
        while len(author_ids) < n_auth:
            a = rng.choices(self.author_ids, cum_weights=self.author_cw)[0]
            if a not in author_ids:
                author_ids.append(a)
        genre_ids = rng.sample(range(1, len(GENRES) + 1), rng.choices([1, 2, 3], [0.5, 0.35, 0.15])[0])
        tags = rng.sample(TAGS, rng.randint(0, 4))
        details = None
        if fmt == "ebook":
            details = {"file_format": rng.choice(["epub", "pdf", "fb2"]), "size_mb": round(rng.uniform(0.5, 60), 2), "drm": rng.random() < 0.3}
        elif fmt == "audiobook":
            details = {"narrator": rng.choice(NARRATORS), "duration_min": rng.randint(60, 1800)}
        copies = []
        if fmt == "print":
            for _ in range(rng.randint(1, 6)):
                cid = next(self.copy_seq)
                br = self.branches[rng.randrange(len(self.branches))]
                status = rng.choices(["available", "on_loan", "in_repair"], [0.7, 0.25, 0.05])[0]
                copies.append((cid, br, f"INV-{br[0]}-{cid:07d}", status))
        reviews = []
        for _ in range(min(40, int(rng.expovariate(1 / 5)))):
            m = self.members[rng.randrange(self.n_members)]
            reviews.append((
                next(self.review_seq), m, rng.choices([1, 2, 3, 4, 5], [0.05, 0.1, 0.2, 0.35, 0.3])[0],
                self.text(5, 15) if rng.random() < 0.7 else None, self.random_date(1095),
            ))
        reviews.sort(key=lambda r: r[4], reverse=True)
        return {
            "book_id": book_id, "isbn": f"978{book_id:010d}", "title": title, "publisher": publisher,
            "year": year, "language": language, "format": fmt, "pages": pages if fmt != "audiobook" else None,
            "description": description, "author_ids": author_ids, "genre_ids": genre_ids, "tags": tags,
            "details": details, "copies": copies, "reviews": reviews, "created_at": self.random_date(3650),
        }

    def to_document(self, b):
        rsum = sum(r[2] for r in b["reviews"])
        rcount = len(b["reviews"])
        doc = {
            "_id": b["book_id"],
            "isbn": b["isbn"],
            "title": b["title"],
            "language": b["language"],
            "format": b["format"],
            "publish_year": b["year"],
            "pages": b["pages"],
            "description": b["description"],
            "publisher": {"id": b["publisher"][0], "name": b["publisher"][1], "city": b["publisher"][2]},
            "authors": [
                {"id": a, "name": f"{self.authors[a - 1][1]} {self.authors[a - 1][2]}", "country": self.authors[a - 1][3]}
                for a in b["author_ids"]
            ],
            "genres": [{"id": g, "name": GENRES[g - 1]} for g in b["genre_ids"]],
            "tags": b["tags"],
            "copies": [
                {"copy_id": c[0], "inventory_code": c[2], "branch": {"id": c[1][0], "name": c[1][1]}, "status": c[3]}
                for c in b["copies"]
            ],
            "rating": {"sum": rsum, "count": rcount, "avg": round(rsum / rcount, 3) if rcount else None},
            "recent_reviews": [
                {"review_id": r[0], "member": {"id": r[1][0], "name": r[1][1]}, "rating": r[2], "comment": r[3], "created_at": r[4]}
                for r in b["reviews"][:5]
            ],
            "created_at": b["created_at"],
        }
        if b["details"]:
            doc["details"] = b["details"]
        return doc

    def make_event(self):
        rng = self.rng
        etype = rng.choices(["search", "view", "reserve", "download"], [0.4, 0.4, 0.1, 0.1])[0]
        member_id = rng.randint(1, self.n_members)
        ev = {"_id": next(self.event_seq), "member_id": member_id, "type": etype, "ts": self.random_date(90), "device": rng.choice(DEVICES)}
        if etype == "search":
            ev["query"] = self.text(1, 3)
            ev["results_count"] = rng.randint(0, 300)
        else:
            ev["book_id"] = rng.choices(self.book_ids, cum_weights=self.book_cw)[0]
            if etype == "view":
                ev["duration_sec"] = rng.randint(3, 600)
            elif etype == "reserve":
                ev["branch_id"] = rng.randint(1, len(self.branches))
        return ev


def run_sql_file(conn, name):
    conn.execute((ROOT / "sql" / name).read_text(encoding="utf-8"))


def copy_rows(cur, sql, rows):
    with cur.copy(sql) as cp:
        for row in rows:
            cp.write_row(row)


def load(books, seed, chunk):
    started = time.perf_counter()
    gen = Generator(books, seed)
    conn = pg_connect(autocommit=False)
    db = mongo_db()

    run_sql_file(conn, "schema.sql")
    conn.commit()
    recreate_collections(db)

    with conn.cursor() as cur:
        copy_rows(cur, "COPY lab2.branches FROM STDIN", gen.branches)
        copy_rows(cur, "COPY lab2.publishers FROM STDIN", gen.publishers)
        copy_rows(cur, "COPY lab2.genres FROM STDIN", gen.genres)
        copy_rows(cur, "COPY lab2.authors FROM STDIN", gen.authors)
        copy_rows(cur, "COPY lab2.members FROM STDIN", gen.members)
    conn.commit()

    t_sql = t_mongo = t_gen = 0.0
    counts = dict(books=0, copies=0, reviews=0, events=0)
    for start in range(1, books + 1, chunk):
        t0 = time.perf_counter()
        batch = [gen.make_book(i) for i in range(start, min(start + chunk, books + 1))]
        docs = [gen.to_document(b) for b in batch]
        t_gen += time.perf_counter() - t0

        t0 = time.perf_counter()
        with conn.cursor() as cur:
            copy_rows(cur, "COPY lab2.books (book_id, isbn, title, publisher_id, publish_year, language, format, pages, description, rating_sum, rating_count, created_at) FROM STDIN", (
                (b["book_id"], b["isbn"], b["title"], b["publisher"][0], b["year"], b["language"], b["format"], b["pages"],
                 b["description"], sum(r[2] for r in b["reviews"]), len(b["reviews"]), b["created_at"]) for b in batch))
            copy_rows(cur, "COPY lab2.book_authors FROM STDIN", ((b["book_id"], a, i + 1) for b in batch for i, a in enumerate(b["author_ids"])))
            copy_rows(cur, "COPY lab2.book_genres FROM STDIN", ((b["book_id"], g) for b in batch for g in b["genre_ids"]))
            copy_rows(cur, "COPY lab2.book_tags FROM STDIN", ((b["book_id"], t) for b in batch for t in b["tags"]))
            copy_rows(cur, "COPY lab2.ebook_details FROM STDIN", (
                (b["book_id"], b["details"]["file_format"], b["details"]["size_mb"], b["details"]["drm"]) for b in batch if b["format"] == "ebook"))
            copy_rows(cur, "COPY lab2.audiobook_details FROM STDIN", (
                (b["book_id"], b["details"]["narrator"], b["details"]["duration_min"]) for b in batch if b["format"] == "audiobook"))
            copy_rows(cur, "COPY lab2.book_copies FROM STDIN", ((c[0], b["book_id"], c[1][0], c[2], c[3]) for b in batch for c in b["copies"]))
            copy_rows(cur, "COPY lab2.reviews FROM STDIN", ((r[0], b["book_id"], r[1][0], r[2], r[3], r[4]) for b in batch for r in b["reviews"]))
            copy_rows(cur, "COPY lab2.book_documents FROM STDIN", ((d["_id"], json.dumps(d, ensure_ascii=False, default=str)) for d in docs))
        conn.commit()
        t_sql += time.perf_counter() - t0

        t0 = time.perf_counter()
        db.books.insert_many(docs, ordered=False)
        reviews = [
            {"_id": r[0], "book_id": b["book_id"], "member": {"id": r[1][0], "name": r[1][1]}, "rating": r[2], "comment": r[3], "created_at": r[4]}
            for b in batch for r in b["reviews"]
        ]
        if reviews:
            db.reviews.insert_many(reviews, ordered=False)
        t_mongo += time.perf_counter() - t0

        counts["books"] += len(batch)
        counts["copies"] += sum(len(b["copies"]) for b in batch)
        counts["reviews"] += len(reviews)
        print(f"  книги: {counts['books']:>8} / {books}", end="\r", flush=True)
    print()

    total_events = books * 10
    for start in range(0, total_events, chunk * 4):
        t0 = time.perf_counter()
        events = [gen.make_event() for _ in range(min(chunk * 4, total_events - start))]
        t_gen += time.perf_counter() - t0

        t0 = time.perf_counter()
        with conn.cursor() as cur:
            copy_rows(cur, "COPY lab2.reader_events FROM STDIN", (
                (e["_id"], e["member_id"], e["type"], e["ts"], e.get("book_id"), e.get("branch_id"), e.get("query"),
                 e.get("results_count"), e["device"], e.get("duration_sec")) for e in events))
        conn.commit()
        t_sql += time.perf_counter() - t0

        t0 = time.perf_counter()
        db.events.insert_many(events, ordered=False)
        t_mongo += time.perf_counter() - t0
        counts["events"] += len(events)
        print(f"  події: {counts['events']:>9} / {total_events}", end="\r", flush=True)
    print()

    t0 = time.perf_counter()
    run_sql_file(conn, "indexes.sql")
    conn.commit()
    t_sql_idx = time.perf_counter() - t0
    t0 = time.perf_counter()
    create_indexes(db)
    t_mongo_idx = time.perf_counter() - t0
    conn.close()

    print(f"Книг: {counts['books']}, примірників: {counts['copies']}, відгуків: {counts['reviews']}, подій: {counts['events']}")
    print(f"Авторів: {gen.n_authors}, читачів: {gen.n_members}, жанрів: {len(GENRES)}")
    print(f"Генерація даних: {t_gen:.1f} c")
    print(f"Завантаження PostgreSQL: {t_sql:.1f} c + індекси {t_sql_idx:.1f} c")
    print(f"Завантаження MongoDB:    {t_mongo:.1f} c + індекси {t_mongo_idx:.1f} c")
    print(f"Разом: {time.perf_counter() - started:.1f} c")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Генерація однакових тестових даних у PostgreSQL та MongoDB")
    parser.add_argument("--books", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--chunk", type=int, default=5_000)
    args = parser.parse_args()
    load(args.books, args.seed, args.chunk)
