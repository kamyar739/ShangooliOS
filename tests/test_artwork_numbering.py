import sqlite3

from app.database import next_artwork_number


def test_next_artwork_number_fills_lowest_sequence_gap():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE artworks (collection_id INTEGER, sequence_number INTEGER)")
    connection.executemany(
        "INSERT INTO artworks VALUES (1, ?)", [(1,), (2,), (4,), (5,), (9,)]
    )
    assert next_artwork_number(connection, 1) == 3
