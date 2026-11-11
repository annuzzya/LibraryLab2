SET search_path TO lab2, public;

CREATE INDEX ix_books_language_year ON books (language, publish_year);
CREATE INDEX ix_books_rating ON books ((rating_sum::numeric / nullif(rating_count, 0)) DESC NULLS LAST);
CREATE INDEX ix_books_fts ON books USING gin (to_tsvector('simple', title || ' ' || coalesce(description, '')));
CREATE INDEX ix_book_authors_author ON book_authors (author_id);
CREATE INDEX ix_book_genres_genre ON book_genres (genre_id);
CREATE INDEX ix_book_tags_tag ON book_tags (tag);
CREATE INDEX ix_copies_book ON book_copies (book_id);
CREATE INDEX ix_copies_branch_status ON book_copies (branch_id, status);
CREATE INDEX ix_reviews_book_created ON reviews (book_id, created_at DESC);
CREATE INDEX ix_events_member_ts ON reader_events (member_id, ts DESC);
CREATE INDEX ix_events_type_ts ON reader_events (event_type, ts DESC);
CREATE INDEX ix_events_ts ON reader_events (ts);

CREATE INDEX ix_book_documents_doc ON book_documents USING gin (doc jsonb_path_ops);

ANALYZE;
