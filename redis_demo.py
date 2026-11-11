import json
import random
import statistics
import time
import uuid

import redis

from benchmark import SQL_BOOK_CARD
from common import REDIS_URL, pg_connect

PREFIX = "lib:"


def title(text):
    print()
    print(text)
    print("-" * len(text))


def clear(r):
    keys = list(r.scan_iter(PREFIX + "*", count=1000))
    if keys:
        r.delete(*keys)


def cache_aside(r, pg):
    title("1. String + TTL: кешування картки книги (cache-aside)")
    cur = pg.cursor()
    max_book = cur.execute("SELECT max(book_id) FROM books WHERE book_id < 10000000").fetchone()[0]
    rng = random.Random(1)
    ids = [rng.randint(1, max_book) for _ in range(300)]

    def get_card(book_id):
        key = f"{PREFIX}book:{book_id}"
        cached = r.get(key)
        if cached is not None:
            return json.loads(cached), True
        row = cur.execute(SQL_BOOK_CARD, (book_id,)).fetchone()
        names = [d.name for d in cur.description]
        card = dict(zip(names, row))
        r.set(key, json.dumps(card, ensure_ascii=False, default=str), ex=300)
        return card, False

    miss, hit = [], []
    for bid in ids:
        t0 = time.perf_counter_ns()
        _, was_hit = get_card(bid)
        (hit if was_hit else miss).append((time.perf_counter_ns() - t0) / 1e6)
    for bid in ids:
        t0 = time.perf_counter_ns()
        _, was_hit = get_card(bid)
        (hit if was_hit else miss).append((time.perf_counter_ns() - t0) / 1e6)

    key = f"{PREFIX}book:{ids[0]}"
    print(f"SET {key} <json> EX 300 -> TTL = {r.ttl(key)} c")
    print(f"GET {key} -> {r.get(key)[:90]}...")
    print(f"Промах кешу (запит у PostgreSQL + SET): медіана {statistics.median(miss):.3f} мс, n={len(miss)}")
    print(f"Влучання в кеш (GET з Redis):           медіана {statistics.median(hit):.3f} мс, n={len(hit)}")
    print(f"Прискорення: ~{statistics.median(miss) / statistics.median(hit):.1f} разів")
    cur.execute("UPDATE books SET title = title WHERE book_id = %s", (ids[0],))
    r.delete(key)
    print(f"Після зміни книги в SQL ключ видаляється (інвалідація): EXISTS {key} -> {r.exists(key)}")


def sessions(r):
    title("2. Hash: сесія читача з автоматичним завершенням")
    token = uuid.uuid4().hex
    key = f"{PREFIX}session:{token}"
    r.hset(key, mapping={"member_id": 42, "name": "Анна Петренко", "branch_id": 1, "role": "reader"})
    r.expire(key, 1800)
    r.hincrby(key, "requests", 1)
    print(f"HSET {key} member_id 42 name ... ; EXPIRE 1800")
    print(f"HGETALL -> {r.hgetall(key)}")
    print(f"HGET name -> {r.hget(key, 'name')}, TTL -> {r.ttl(key)} c")


def top_books(r, pg):
    title("3. Sorted set: рейтинг найпопулярніших книг за переглядами")
    key = f"{PREFIX}top:views:2026-10"
    cur = pg.cursor()
    rows = cur.execute("""
        SELECT book_id FROM reader_events
         WHERE event_type = 'view' AND ts >= '2026-09-24' AND ts < '2026-10-01'
    """).fetchall()
    t0 = time.perf_counter()
    pipe = r.pipeline(transaction=False)
    for (book_id,) in rows:
        pipe.zincrby(key, 1, f"book:{book_id}")
    pipe.execute()
    elapsed = time.perf_counter() - t0
    print(f"ZINCRBY {key} 1 book:<id>  x{len(rows)} переглядів за тиждень ({elapsed:.2f} c через pipeline)")
    print(f"ZCARD -> {r.zcard(key)} різних книг")
    print("ZREVRANGE 0 4 WITHSCORES ->")
    for member, score in r.zrevrange(key, 0, 4, withscores=True):
        print(f"   {member:<14} {int(score)} переглядів")
    first = r.zrevrange(key, 0, 0)[0]
    print(f"ZREVRANK {first} -> {r.zrevrank(key, first)} (місце в рейтингу, з 0)")
    t0 = time.perf_counter_ns()
    for _ in range(200):
        r.zrevrange(key, 0, 9, withscores=True)
    redis_ms = (time.perf_counter_ns() - t0) / 1e6 / 200
    t0 = time.perf_counter_ns()
    for _ in range(5):
        cur.execute("""
            SELECT book_id, count(*) FROM reader_events
             WHERE event_type = 'view' AND ts >= '2026-09-24' AND ts < '2026-10-01'
             GROUP BY book_id ORDER BY count(*) DESC LIMIT 10
        """).fetchall()
    sql_ms = (time.perf_counter_ns() - t0) / 1e6 / 5
    print(f"Топ-10: Redis ZREVRANGE {redis_ms:.3f} мс  vs  SQL GROUP BY по подіях {sql_ms:.1f} мс")


def notifications(r):
    title("4. List: черга повідомлень читачу (FIFO)")
    key = f"{PREFIX}notify:42"
    r.rpush(key, "Книга «Місто» чекає на вас у Центральній бібліотеці", "Термін повернення «Інтернат» спливає завтра",
            "Нагадування: майстер-клас з SQL у суботу")
    print(f"RPUSH {key} ... -> LLEN = {r.llen(key)}")
    print(f"LRANGE 0 -1 -> {r.lrange(key, 0, -1)}")
    print(f"LPOP -> {r.lpop(key)}  (обробник забрав перше повідомлення)")
    print(f"LLEN -> {r.llen(key)}")


def genres_sets(r):
    title("5. Set: улюблені жанри читачів і спільні інтереси")
    a, b = f"{PREFIX}fav:42", f"{PREFIX}fav:77"
    r.sadd(a, "Роман", "Детектив", "Історія", "Програмування")
    r.sadd(b, "Програмування", "Фентезі", "Історія")
    print(f"SADD {a} Роман Детектив Історія Програмування")
    print(f"SADD {b} Програмування Фентезі Історія")
    print(f"SINTER -> {sorted(r.sinter(a, b))}  (спільні жанри для рекомендацій)")
    print(f"SUNION -> {sorted(r.sunion(a, b))}")
    print(f"SISMEMBER {a} Фентезі -> {bool(r.sismember(a, 'Фентезі'))}")


def rate_limit(r):
    title("6. INCR + EXPIRE: обмеження кількості бронювань (5 на хвилину)")
    member = 42
    window = int(time.time() // 60)
    key = f"{PREFIX}rate:reserve:{member}:{window}"
    for attempt in range(1, 8):
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, 60)
        count, _ = pipe.execute()
        status = "дозволено" if count <= 5 else "відхилено (429 Too Many Requests)"
        print(f"   спроба {attempt}: INCR {key} -> {count} -> {status}")


def transaction(r):
    title("7. MULTI/EXEC + WATCH: атомарне бронювання останнього примірника")
    stock = f"{PREFIX}stock:book:5:branch:1"
    holds = f"{PREFIX}holds:book:5"
    r.set(stock, 1)

    def reserve(member_id):
        with r.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(stock)
                    left = int(pipe.get(stock) or 0)
                    if left <= 0:
                        pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.decr(stock)
                    pipe.sadd(holds, member_id)
                    pipe.execute()
                    return True
                except redis.WatchError:
                    continue

    print(f"SET {stock} 1")
    print(f"   читач 42 бронює -> {'успішно' if reserve(42) else 'немає примірників'}")
    print(f"   читач 77 бронює -> {'успішно' if reserve(77) else 'немає примірників'}")
    print(f"GET {stock} -> {r.get(stock)}, SMEMBERS {holds} -> {r.smembers(holds)}")


def main():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    print(f"Redis {r.info('server')['redis_version']}, PING -> {r.ping()}")
    clear(r)
    pg = pg_connect()
    cache_aside(r, pg)
    sessions(r)
    top_books(r, pg)
    notifications(r)
    genres_sets(r)
    rate_limit(r)
    transaction(r)
    print()
    print(f"Ключів з префіксом {PREFIX}: {sum(1 for _ in r.scan_iter(PREFIX + '*'))}, пам'ять Redis: {r.info('memory')['used_memory_human']}")


if __name__ == "__main__":
    main()
