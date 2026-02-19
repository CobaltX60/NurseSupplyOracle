# Source Files and Rebuild

## Source file location

**Place all PDF (and other) source documents in:**

```
scripts/source_files/
```

- The application **does not** read from the project root `source_files/` folder.
- Only files in **`scripts/source_files/`** are used when you run a rebuild.
- Supported for rebuild: **PDF** (`.pdf`). Add more types in `scripts/rebuild.py` if needed.

## No migration of existing content

Existing chunk JSON and FAISS index files in the project root are **not** used. The app loads only from:

- **SQLite:** `data/instrument_oracle.db`
- **FAISS index:** `data/faiss_index.idx`

Both are created and updated by the rebuild script.

## When does data get built?

- **Application start:** The app **starts and runs** using whatever is already in SQLite and the FAISS index. It **does not** rebuild or re-ingest on startup.
- **Rebuild only when prompted:** To refresh content, you must run a rebuild yourself:
  ```bash
  python scripts/rebuild.py
  ```
  This will:
  1. Scan `scripts/source_files/` for PDFs
  2. Extract text, chunk it, and write to `data/instrument_oracle.db`
  3. Build embeddings and save `data/faiss_index.idx`
  4. Replace existing data (full rebuild)

After a rebuild, **restart the chat server** so it loads the new data. (Or add a reload endpoint later.)

## Workflow summary

1. Put PDFs in **`scripts/source_files/`**.
2. Run **`python scripts/rebuild.py`** when you want to refresh the library.
3. Restart the chat server (`python scripts/chat_server.py`) so it picks up the new DB and index.
4. Use the UI on port 3001 to ask questions.

If no rebuild has been run (or `data/` is empty), the app still starts; answering a question will return a message asking you to run a rebuild and add source files.
