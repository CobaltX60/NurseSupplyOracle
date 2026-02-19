"""
SQLite schema and helpers for Instrument Oracle.
DB path: data/instrument_oracle.db (relative to project root).
"""
import os
import sqlite3

# Project root (parent of scripts/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "instrument_oracle.db")
FAISS_INDEX_PATH = os.path.join(DATA_DIR, "faiss_index.idx")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def get_connection():
    ensure_data_dir()
    return sqlite3.connect(DB_PATH)


def init_schema(conn):
    conn.executescript("""
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
    """)
    conn.commit()


def init_db():
    """Create data dir and schema. Idempotent."""
    ensure_data_dir()
    conn = get_connection()
    try:
        init_schema(conn)
    finally:
        conn.close()
