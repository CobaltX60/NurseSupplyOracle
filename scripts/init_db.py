#!/usr/bin/env python3
"""
Initialize or update the Instrument Oracle database schema.
Creates all tables (sources, chunks, images, catalog_config, catalog_samples, products, product_images) if they do not exist.
Safe to run multiple times; does not delete existing data.

Uses the same path as the chat server: data/instrument_oracle.db under the project root (parent of scripts/).
Run from anywhere: python scripts/init_db.py
"""
import os
import sqlite3

# Same path logic as chat_server.py and db.py: project root = parent of scripts/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "instrument_oracle.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    profile_path TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    page_number INTEGER,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    type TEXT DEFAULT 'text',
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_order ON chunks(id);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    page_number INTEGER NOT NULL,
    image_index INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    bbox_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_id, page_number, image_index)
);
CREATE INDEX IF NOT EXISTS idx_images_source_page ON images(source_id, page_number);

CREATE TABLE IF NOT EXISTS page_blocks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    page_number INTEGER NOT NULL,
    block_index INTEGER NOT NULL,
    bbox_json TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_page_blocks_source_page ON page_blocks(source_id, page_number);

CREATE TABLE IF NOT EXISTS catalog_config (
    source_id INTEGER PRIMARY KEY REFERENCES sources(id),
    config_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS catalog_profiles (
    source_id INTEGER PRIMARY KEY REFERENCES sources(id),
    catalog_id TEXT,
    source_filename TEXT NOT NULL,
    manufacturer TEXT,
    profile_json TEXT NOT NULL,
    analyzed_at TEXT,
    analyzed_by_model TEXT,
    sample_pages TEXT,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS catalog_samples (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    page_number INTEGER,
    sample_type TEXT NOT NULL,
    value_text TEXT NOT NULL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_catalog_samples_source ON catalog_samples(source_id);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    page_number INTEGER,
    manufacturer TEXT,
    manufacturer_part_number TEXT NOT NULL,
    product_name TEXT,
    description TEXT,
    secondary_description TEXT,
    category TEXT,
    language TEXT DEFAULT 'en',
    verification_status TEXT DEFAULT 'unverified',
    raw_snippet TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_products_source ON products(source_id);

CREATE TABLE IF NOT EXISTS product_images (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    image_id INTEGER NOT NULL REFERENCES images(id),
    display_order INTEGER DEFAULT 0,
    UNIQUE(product_id, image_id)
);
CREATE INDEX IF NOT EXISTS idx_product_images_product ON product_images(product_id);
"""


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Database file: {DB_PATH}")
    if not os.path.isabs(DB_PATH):
        print(f"  (resolved absolute: {os.path.abspath(DB_PATH)})")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        # Ensure products.category exists (for DBs created before category was added)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        if cur.fetchone():
            info = conn.execute("PRAGMA table_info(products)").fetchall()
            columns = [row[1] for row in info]
            if "category" not in columns:
                conn.execute("ALTER TABLE products ADD COLUMN category TEXT")
                conn.commit()
                print("Added column 'category' to table 'products'.")
        # Ensure images.bbox_json exists (for layout-based image–product proximity)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='images'")
        if cur.fetchone():
            info = conn.execute("PRAGMA table_info(images)").fetchall()
            columns = [row[1] for row in info]
            if "bbox_json" not in columns:
                conn.execute("ALTER TABLE images ADD COLUMN bbox_json TEXT")
                conn.commit()
                print("Added column 'bbox_json' to table 'images'.")
        # Ensure sources.profile_path exists (catalog profile path per source)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
        if cur.fetchone():
            info = conn.execute("PRAGMA table_info(sources)").fetchall()
            columns = [row[1] for row in info]
            if "profile_path" not in columns:
                conn.execute("ALTER TABLE sources ADD COLUMN profile_path TEXT")
                conn.commit()
                print("Added column 'profile_path' to table 'sources'.")
        # Ensure catalog_profiles table exists (analysis-generated profiles)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='catalog_profiles'")
        if not cur.fetchone():
            conn.execute("""
                CREATE TABLE catalog_profiles (
                    source_id INTEGER PRIMARY KEY REFERENCES sources(id),
                    catalog_id TEXT,
                    source_filename TEXT NOT NULL,
                    manufacturer TEXT,
                    profile_json TEXT NOT NULL,
                    analyzed_at TEXT,
                    analyzed_by_model TEXT,
                    sample_pages TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            conn.commit()
            print("Created table 'catalog_profiles'.")
        # Verify products table exists
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        if cur.fetchone():
            print("Database initialized successfully. Table 'products' exists.")
        else:
            print("Warning: schema ran but 'products' table not found.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
