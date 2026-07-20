PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id INTEGER,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    collection_type TEXT NOT NULL,
    vertical TEXT NOT NULL,
    target_artwork_count INTEGER,
    etsy_section_name TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (brand_id) REFERENCES brands(id)
);

CREATE TABLE IF NOT EXISTS artworks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artwork_code TEXT NOT NULL UNIQUE,
    collection_id INTEGER NOT NULL,
    sequence_number INTEGER NOT NULL,
    public_title TEXT NOT NULL,
    working_title TEXT,
    theme TEXT,
    story TEXT,
    status TEXT NOT NULL DEFAULT 'idea',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (collection_id) REFERENCES collections(id),
    UNIQUE (collection_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_collections_brand_id
ON collections(brand_id);

CREATE INDEX IF NOT EXISTS idx_artworks_collection_id
ON artworks(collection_id);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artwork_id INTEGER NOT NULL,
    marketplace TEXT NOT NULL DEFAULT 'Etsy',
    product TEXT NOT NULL DEFAULT 'Poster',
    title TEXT NOT NULL,
    description TEXT,
    tags TEXT,
    price_cents INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    status TEXT NOT NULL DEFAULT 'draft',
    marketplace_url TEXT,
    external_listing_id TEXT,
    published_at TEXT,
    printify_product_url TEXT,
    printify_product_id TEXT,
    printify_provider TEXT,
    printify_sizes TEXT,
    printify_base_cost_cents INTEGER,
    printify_etsy_connected_at TEXT,
    printify_publish_requested_at TEXT,
    etsy_last_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (artwork_id) REFERENCES artworks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_listings_artwork_id
ON listings(artwork_id);

CREATE INDEX IF NOT EXISTS idx_listings_status
ON listings(status);
