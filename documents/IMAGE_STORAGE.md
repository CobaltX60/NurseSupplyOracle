# Where Extracted Images Are Stored

## File system

All images extracted during **rebuild** are written under:

```
<project_root>/data/images/<source_id>/page_<page_number>_<image_index>.<ext>
```

- **source_id**: ID of the catalog (source) in the DB (e.g. `1`, `2`).
- **page_number**: 1-based page number (e.g. `24`).
- **image_index**: 0-based index of the image on that page (e.g. `0` … `8` for 9 images).
- **ext**: `png`, `jpeg`, or `gif`.

Example for catalog ID 1, page 24, with 9 images (4 direct + 5 from Form XObjects):

- `data/images/1/page_24_0.png` … `data/images/1/page_24_8.png`

## Database

- **`images`** table: one row per extracted image  
  - `source_id`, `page_number`, `image_index`, `file_path`, `width`, `height`  
  - `file_path` is relative, e.g. `images/1/page_24_4.png`.

- **`product_images`** table: links products to images  
  - `product_id`, `image_id`, `display_order`  
  - Filled when you run **Build product listing** (or assign images manually).

## How the app uses them

- **Catalog content** (list of pages and images):  
  `GET /api/catalogs/<source_id>/content`  
  Returns every image for that catalog from `images` (by page and `image_index`). So all 9 images for page 24 appear here if they were extracted.

- **Serving a single image**:  
  `GET /api/image/<source_id>/<page_number>/<image_index>`  
  Looks up `file_path` in `images` and sends the file from `data/`.

- **Images on a product**:  
  Product detail and chat use `product_images` → `images`; only images linked in `product_images` show as “product images”.

## How to verify the 5 orphan images

1. **After a full rebuild**, check that page 24 has 9 images on disk:
   - List: `data/images/<source_id>/page_24_*`
   - You should see `page_24_0` … `page_24_8` if the 5 orphans were assigned to that page.

2. **In the DB** (e.g. SQLite shell or a query script):
   ```sql
   SELECT id, source_id, page_number, image_index, file_path
   FROM images
   WHERE source_id = <your_catalog_id> AND page_number = 24
   ORDER BY image_index;
   ```
   You should see 9 rows if the 5 orphans were extracted and attached to page 24.

3. **In the UI**:  
   Open the catalog and go to page 24. The catalog content API returns all images for that page; the page should list 9 images (including the 5 that were orphans).  
   They will only show as **product** images for specific items after **Build product listing** (or manual assign). Build links by index: product 0 ↔ image 0, product 1 ↔ image 1, etc., so extra images (e.g. 4–8) may need to be assigned to products manually.

If you only see 4 images for page 24 on disk and in the DB, the orphan extraction (Form XObject stream search) did not find those xrefs on that page; the PDF may reference them in a different format, and we can add logging or adjust the search pattern.
