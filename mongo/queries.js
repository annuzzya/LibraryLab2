use("library_lab2");

db.books.findOne({ _id: 1 });

db.books.find(
  { "authors.name": /Шевченко/, language: "uk" },
  { title: 1, publish_year: 1, "authors.name": 1, "rating.avg": 1 }
).sort({ "rating.avg": -1 }).limit(10);

db.books.find(
  {
    "genres.id": 1,
    language: "uk",
    publish_year: { $gte: 1990, $lte: 2000 },
    copies: { $elemMatch: { "branch.id": 1, status: "available" } }
  },
  { title: 1, "authors.name": 1, "rating.avg": 1 }
).sort({ "rating.avg": -1 }).limit(20);

db.books.find({ $text: { $search: "детектив" } }, { title: 1 }).limit(10);

db.books.find({ format: "ebook", "details.drm": false }, { title: 1, details: 1 }).limit(5);
db.books.find({ format: "audiobook", "details.duration_min": { $gt: 600 } }, { title: 1, details: 1 }).limit(5);

db.books.find({ tags: { $all: ["бестселер", "класика"] } }, { title: 1, tags: 1 }).limit(5);

db.books.aggregate([
  { $unwind: "$genres" },
  { $group: { _id: "$genres.name", books: { $sum: 1 }, avg_rating: { $avg: "$rating.avg" } } },
  { $sort: { books: -1 } },
  { $limit: 10 }
]);

db.books.aggregate([
  { $unwind: "$copies" },
  { $group: { _id: { branch: "$copies.branch.name", status: "$copies.status" }, copies: { $sum: 1 } } },
  { $sort: { "_id.branch": 1, "_id.status": 1 } }
]);

db.reviews.find({ book_id: 1 }).sort({ created_at: -1 }).limit(5);

db.events.find({ member_id: 42 }).sort({ ts: -1 }).limit(20);

db.events.aggregate([
  { $match: { ts: { $gte: ISODate("2026-09-24T00:00:00Z"), $lt: ISODate("2026-10-01T00:00:00Z") } } },
  { $group: { _id: "$type", events: { $sum: 1 } } },
  { $sort: { events: -1 } }
]);

db.books.updateOne(
  { "copies.copy_id": 1 },
  { $set: { "copies.$[c].status": "on_loan" } },
  { arrayFilters: [{ "c.copy_id": 1 }] }
);

db.books.updateOne(
  { _id: 1 },
  { $push: { tags: "рекомендує_бібліотекар" } }
);

db.books.find({ _id: 1 }).explain("executionStats");
db.books.getIndexes();
db.stats();
