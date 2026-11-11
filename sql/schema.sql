DROP SCHEMA IF EXISTS lab2 CASCADE;
CREATE SCHEMA lab2;
SET search_path TO lab2, public;

CREATE TABLE branches (
    branch_id   INT PRIMARY KEY,
    name        VARCHAR(150) NOT NULL,
    city        VARCHAR(80)  NOT NULL
);

CREATE TABLE publishers (
    publisher_id INT PRIMARY KEY,
    name         VARCHAR(150) NOT NULL,
    city         VARCHAR(80)
);

CREATE TABLE authors (
    author_id   INT PRIMARY KEY,
    first_name  VARCHAR(60) NOT NULL,
    last_name   VARCHAR(60) NOT NULL,
    country     VARCHAR(60)
);

CREATE TABLE genres (
    genre_id    INT PRIMARY KEY,
    name        VARCHAR(80) NOT NULL UNIQUE
);

CREATE TABLE members (
    member_id   INT PRIMARY KEY,
    full_name   VARCHAR(120) NOT NULL,
    email       VARCHAR(120) NOT NULL
);

CREATE TABLE books (
    book_id       INT PRIMARY KEY,
    isbn          VARCHAR(17) NOT NULL,
    title         VARCHAR(255) NOT NULL,
    publisher_id  INT REFERENCES publishers(publisher_id),
    publish_year  SMALLINT,
    language      VARCHAR(10) NOT NULL,
    format        VARCHAR(20) NOT NULL CHECK (format IN ('print', 'ebook', 'audiobook')),
    pages         INT,
    description   TEXT,
    rating_sum    INT NOT NULL DEFAULT 0,
    rating_count  INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE book_authors (
    book_id      INT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
    author_id    INT NOT NULL REFERENCES authors(author_id),
    author_order SMALLINT NOT NULL,
    PRIMARY KEY (book_id, author_id)
);

CREATE TABLE book_genres (
    book_id   INT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
    genre_id  INT NOT NULL REFERENCES genres(genre_id),
    PRIMARY KEY (book_id, genre_id)
);

CREATE TABLE book_tags (
    book_id  INT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
    tag      VARCHAR(40) NOT NULL,
    PRIMARY KEY (book_id, tag)
);

CREATE TABLE ebook_details (
    book_id     INT PRIMARY KEY REFERENCES books(book_id) ON DELETE CASCADE,
    file_format VARCHAR(10) NOT NULL,
    size_mb     NUMERIC(6,2) NOT NULL,
    drm         BOOLEAN NOT NULL
);

CREATE TABLE audiobook_details (
    book_id      INT PRIMARY KEY REFERENCES books(book_id) ON DELETE CASCADE,
    narrator     VARCHAR(120) NOT NULL,
    duration_min INT NOT NULL
);

CREATE TABLE book_copies (
    copy_id        INT PRIMARY KEY,
    book_id        INT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
    branch_id      INT NOT NULL REFERENCES branches(branch_id),
    inventory_code VARCHAR(30) NOT NULL UNIQUE,
    status         VARCHAR(20) NOT NULL
);

CREATE TABLE reviews (
    review_id   BIGINT PRIMARY KEY,
    book_id     INT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
    member_id   INT NOT NULL REFERENCES members(member_id),
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE reader_events (
    event_id      BIGINT PRIMARY KEY,
    member_id     INT NOT NULL,
    event_type    VARCHAR(20) NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    book_id       INT,
    branch_id     INT,
    query_text    VARCHAR(200),
    results_count INT,
    device        VARCHAR(20),
    duration_sec  INT
);

CREATE TABLE book_documents (
    book_id  INT PRIMARY KEY,
    doc      JSONB NOT NULL
);
