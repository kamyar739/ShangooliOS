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
    prompt TEXT,
    cover_image_path TEXT,
    cover_approved INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER,
    default_price_tier_1_cents INTEGER NOT NULL DEFAULT 2900,
    default_price_tier_2_cents INTEGER NOT NULL DEFAULT 3400,
    default_price_tier_3_cents INTEGER NOT NULL DEFAULT 3900,
    default_price_tier_4_cents INTEGER NOT NULL DEFAULT 4600,
    default_price_tier_5_cents INTEGER NOT NULL DEFAULT 5800,
    default_price_tier_6_cents INTEGER NOT NULL DEFAULT 7200,
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
    description TEXT,
    story TEXT,
    prompt TEXT,
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
    etsy_state TEXT,
    etsy_inventory_quantity INTEGER,
    etsy_inventory_restore_quantity INTEGER,
    etsy_inventory_updated_at TEXT,
    etsy_paused_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (artwork_id) REFERENCES artworks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_listings_artwork_id
ON listings(artwork_id);

CREATE INDEX IF NOT EXISTS idx_listings_status
ON listings(status);

CREATE TABLE IF NOT EXISTS standalone_designs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    message TEXT,
    description TEXT,
    tags TEXT,
    source_filename TEXT NOT NULL,
    source_original_filename TEXT,
    image_width INTEGER,
    image_height INTEGER,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS standalone_design_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    design_id INTEGER NOT NULL,
    product_type TEXT NOT NULL DEFAULT 'mug_11oz',
    blueprint_version INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    description TEXT,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    blueprint_id INTEGER NOT NULL,
    provider_id INTEGER NOT NULL,
    provider_name TEXT NOT NULL,
    variant_id INTEGER NOT NULL,
    variant_title TEXT NOT NULL,
    placement_x REAL NOT NULL DEFAULT 0.5,
    placement_y REAL NOT NULL DEFAULT 0.5,
    placement_scale REAL NOT NULL DEFAULT 0.45,
    placement_mode TEXT NOT NULL DEFAULT 'front',
    opposite_source_filename TEXT,
    production_asset_filename TEXT,
    printify_product_id TEXT,
    printify_product_url TEXT,
    printify_base_cost_cents INTEGER,
    external_state TEXT NOT NULL DEFAULT 'not_sent',
    external_message TEXT,
    etsy_listing_id TEXT,
    etsy_listing_url TEXT,
    etsy_state TEXT,
    etsy_paused_at TEXT,
    marketplace_checked_at TEXT,
    etsy_last_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (design_id) REFERENCES standalone_designs(id) ON DELETE CASCADE,
    UNIQUE (design_id, product_type)
);

CREATE INDEX IF NOT EXISTS idx_standalone_design_products_design
ON standalone_design_products(design_id);
