'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'

// Load images directly from Flask when set (avoids hundreds of GET /api/image/... lines in Next.js dev server).
// In development, default to localhost:5001 so catalog-setup doesn't flood Next.js logs.
const FLASK_IMAGE_BASE =
  (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_FLASK_URL) ||
  (typeof process !== 'undefined' && process.env.NODE_ENV === 'development' ? 'http://localhost:5001' : '')
function imageSrc(url: string): string {
  if (url.startsWith('/api/image') && FLASK_IMAGE_BASE) return FLASK_IMAGE_BASE + url
  return url
}

type Catalog = { id: number; name: string }
type PageContent = { page_number: number; chunks: { id: number; chunk_index: number; text: string }[]; images: { image_index: number; url: string }[] }
type ProductImage = { image_id: number; source_id: number; page_number: number; image_index: number; url: string; display_order: number }
type Product = {
  id: number
  source_id: number
  page_number: number | null
  manufacturer: string | null
  manufacturer_part_number: string
  product_name: string | null
  description: string | null
  secondary_description: string | null
  category: string | null
  language: string
  verification_status: string
  images: ProductImage[]
  created_at?: string
  updated_at?: string
}

export default function CatalogSetupPage() {
  const [catalogs, setCatalogs] = useState<Catalog[]>([])
  const [selectedId, setSelectedId] = useState<string>('')
  const [content, setContent] = useState<{ catalog_id: number; catalog_name: string; pages: PageContent[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'content' | 'profile' | 'products'>('content')
  const [products, setProducts] = useState<Product[]>([])

  // Analysis profile (from Analyze Catalog Layout; zone/column detection in profile JSON)
  type ProfileStatus = { status: string | null; analyzed_at?: string; analyzed_by_model?: string; catalog_id?: string; manufacturer?: string; last_rebuild_at?: string | null }
  const [profileStatus, setProfileStatus] = useState<ProfileStatus | null>(null)
  const [analyzeLoading, setAnalyzeLoading] = useState(false)
  type ValidationZone = { zone_index: number; columns_count: number; columns: Array<{ family_name: string; mpns: string[]; product_count: number } | null>; images: Array<{ width_pt: number; height_pt: number; column_index: number; association: string; assigned_to: string | null }> }
  const [analyzeResult, setAnalyzeResult] = useState<{
    summary?: { zone_detection?: string; catalog_number_patterns_count?: number; confidence_scores?: Record<string, number>; low_confidence?: string[] };
    progress?: string[];
    validation_report?: { page_number: number; report: { zones_count: number; per_zone: ValidationZone[] } }[];
  } | null>(null)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)
  const [showProfileEditor, setShowProfileEditor] = useState(false)
  const [profileAnalysisJson, setProfileAnalysisJson] = useState('')
  const [profileAnalysisDirty, setProfileAnalysisDirty] = useState(false)
  const [profileAnalysisSaving, setProfileAnalysisSaving] = useState(false)
  const [rebuildLoading, setRebuildLoading] = useState(false)
  const [rebuildError, setRebuildError] = useState<string | null>(null)

  // Add-product form
  const [productPartNumber, setProductPartNumber] = useState('')
  const [productName, setProductName] = useState('')
  const [productDescription, setProductDescription] = useState('')
  const [productSecondaryDesc, setProductSecondaryDesc] = useState('')
  const [productCategory, setProductCategory] = useState('')
  const [productPageNumber, setProductPageNumber] = useState('')
  const [productManufacturer, setProductManufacturer] = useState('')
  const [productSubmitting, setProductSubmitting] = useState(false)
  const [assignImageForProductId, setAssignImageForProductId] = useState<number | null>(null)
  const [buildListingLoading, setBuildListingLoading] = useState(false)
  const [buildListingResult, setBuildListingResult] = useState<{ created: number; pages_processed: number; errors: string[] } | null>(null)
  const [buildReplaceExisting, setBuildReplaceExisting] = useState(true)
  const [buildSinglePageNumber, setBuildSinglePageNumber] = useState('')
  const [buildSinglePageResult, setBuildSinglePageResult] = useState<{ created: number; page_number: number; errors: string[] } | null>(null)
  const [buildByPageProgress, setBuildByPageProgress] = useState<{ current: number; total: number; created: number; errors: string[] } | null>(null)

  // Pagination: Content tab (catalog pages) and Products tab
  const [contentPage, setContentPage] = useState(1)
  const contentPageSize = 5
  const [productsPage, setProductsPage] = useState(1)
  const productsPageSize = 15

  // Assign part number to image (from Content tab click) — opens modal
  const [assigningImage, setAssigningImage] = useState<{ pageNumber: number; imageIndex: number; imageUrl?: string } | null>(null)
  const [assignPartNumber, setAssignPartNumber] = useState('')
  const [assignProductName, setAssignProductName] = useState('')
  const [assignDescription, setAssignDescription] = useState('')
  const [assignSecondaryDescription, setAssignSecondaryDescription] = useState('')
  const [assignCategory, setAssignCategory] = useState('')
  const [assignSubmitting, setAssignSubmitting] = useState(false)

  const loadCatalogs = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch('/api/catalogs')
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Failed to load catalogs')
      setCatalogs(data)
      if (data.length && !selectedId) setSelectedId(String(data[0].id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load catalogs')
    }
  }, [selectedId])

  useEffect(() => {
    loadCatalogs()
  }, [])

  const loadCatalogData = useCallback(async (id: string) => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const [contentRes, productsRes, statusRes] = await Promise.all([
        fetch(`/api/catalogs/${id}/content`),
        fetch(`/api/catalogs/${id}/products`),
        fetch(`/api/catalogs/${id}/profile-status`),
      ])
      const contentData = await contentRes.json()
      const productsData = await productsRes.json()
      const statusData = await statusRes.json()
      if (!contentRes.ok) throw new Error(contentData.error || 'Failed to load content')
      if (!productsRes.ok) throw new Error(productsData.error || 'Failed to load products')
      setContent(contentData)
      setProducts(
        Array.isArray(productsData)
          ? (productsData as Product[]).map((p) => ({ ...p, images: Array.isArray(p.images) ? p.images : [] }))
          : []
      )
      setProfileStatus(statusData ?? null)
      setAnalyzeResult(null)
      setAnalyzeError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load catalog data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selectedId) loadCatalogData(selectedId)
    else setContent(null)
    setContentPage(1)
    setProductsPage(1)
  }, [selectedId, loadCatalogData])

  const [analyzeSamplePages, setAnalyzeSamplePages] = useState('')

  const handleAnalyzeCatalog = async () => {
    if (!selectedId) return
    setAnalyzeLoading(true)
    setAnalyzeError(null)
    setAnalyzeResult(null)
    try {
      const sample_pages: number[] = analyzeSamplePages.trim()
        ? analyzeSamplePages.split(/[\s,]+/).map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n) && n >= 1)
        : []
      const res = await fetch(`/api/catalogs/${selectedId}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sample_pages.length ? { sample_pages } : {}),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Analysis failed')
      setAnalyzeResult(data)
      loadCatalogData(selectedId)
    } catch (e) {
      setAnalyzeError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setAnalyzeLoading(false)
    }
  }

  const handleLoadProfileEditor = async () => {
    if (!selectedId) return
    try {
      const res = await fetch(`/api/catalogs/${selectedId}/profile-analysis`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Failed to load')
      setProfileAnalysisJson(JSON.stringify(data, null, 2))
      setProfileAnalysisDirty(false)
      setShowProfileEditor(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load profile')
    }
  }

  const handleSaveProfileAnalysis = async () => {
    if (!selectedId) return
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(profileAnalysisJson)
    } catch {
      setError('Invalid JSON in profile')
      return
    }
    setProfileAnalysisSaving(true)
    setError(null)
    try {
      const res = await fetch(`/api/catalogs/${selectedId}/profile-analysis`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Failed to save')
      setProfileAnalysisDirty(false)
      setProfileStatus((prev) => (prev ? { ...prev, status: 'verified' } : { status: 'verified' }))
      loadCatalogData(selectedId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save profile')
    } finally {
      setProfileAnalysisSaving(false)
    }
  }

  const handleRebuildCatalog = async () => {
    if (!selectedId) return
    setRebuildLoading(true)
    setRebuildError(null)
    setError(null)
    try {
      const res = await fetch(`/api/catalogs/${selectedId}/rebuild`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Rebuild failed')
      await loadCatalogData(selectedId)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Rebuild failed'
      setRebuildError(msg)
    } finally {
      setRebuildLoading(false)
    }
  }

  const handleAddProduct = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedId || !productPartNumber.trim()) return
    setProductSubmitting(true)
    setError(null)
    try {
      const res = await fetch(`/api/catalogs/${selectedId}/products`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          manufacturer_part_number: productPartNumber.trim(),
          product_name: productName.trim() || undefined,
          description: productDescription.trim() || undefined,
          secondary_description: productSecondaryDesc.trim() || undefined,
          category: productCategory.trim() || undefined,
          page_number: productPageNumber.trim() ? parseInt(productPageNumber, 10) : undefined,
          manufacturer: productManufacturer.trim() || undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Failed to add product')
      setProductPartNumber('')
      setProductName('')
      setProductDescription('')
      setProductSecondaryDesc('')
      setProductCategory('')
      setProductPageNumber('')
      setProductManufacturer('')
      loadCatalogData(selectedId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to add product')
    } finally {
      setProductSubmitting(false)
    }
  }

  const handleAssignImage = async (productId: number, sourceId: number, pageNumber: number, imageIndex: number) => {
    setError(null)
    try {
      const res = await fetch(`/api/products/${productId}/images`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_id: sourceId, page_number: pageNumber, image_index: imageIndex }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Failed to assign image')
      setAssignImageForProductId(null)
      loadCatalogData(selectedId!)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to assign image')
    }
  }

  const handleExport = (format: 'json' | 'csv') => {
    if (!selectedId) return
    const url = `/api/catalogs/${selectedId}/products/export?format=${format}`
    window.open(url, '_blank')
  }

  const handleBuildProductListing = async () => {
    if (!selectedId) return
    setBuildListingLoading(true)
    setBuildListingResult(null)
    setBuildByPageProgress(null)
    setError(null)
    try {
      const res = await fetch(`/api/catalogs/${selectedId}/build-product-listing`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ replace: buildReplaceExisting }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || data.errors?.[0] || 'Build failed')
      setBuildListingResult({ created: data.created ?? 0, pages_processed: data.pages_processed ?? 0, errors: data.errors ?? [] })
      loadCatalogData(selectedId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build product listing failed')
    } finally {
      setBuildListingLoading(false)
    }
  }

  const handleBuildSinglePage = async () => {
    if (!selectedId) return
    const pageNum = buildSinglePageNumber.trim() ? parseInt(buildSinglePageNumber.trim(), 10) : null
    if (pageNum == null || Number.isNaN(pageNum) || pageNum < 1) {
      setError('Enter a valid page number (1 or higher)')
      return
    }
    setBuildListingLoading(true)
    setBuildSinglePageResult(null)
    setError(null)
    try {
      const res = await fetch(`/api/catalogs/${selectedId}/build-product-listing/page/${pageNum}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ replace: buildReplaceExisting }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || data.errors?.[0] || 'Single-page build failed')
      setBuildSinglePageResult({
        created: data.created ?? 0,
        page_number: data.page_number ?? pageNum,
        errors: data.errors ?? [],
      })
      loadCatalogData(selectedId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Single-page build failed')
    } finally {
      setBuildListingLoading(false)
    }
  }

  const handleBuildProductListingByPage = async () => {
    if (!selectedId || !content?.pages?.length) return
    const sortedPages = [...content.pages].sort((a, b) => a.page_number - b.page_number)
    setBuildListingLoading(true)
    setBuildListingResult(null)
    setBuildByPageProgress({ current: 0, total: sortedPages.length, created: 0, errors: [] })
    setError(null)
    try {
      if (buildReplaceExisting) {
        const clearRes = await fetch(`/api/catalogs/${selectedId}/build-product-listing/clear`, { method: 'POST' })
        if (!clearRes.ok) {
          const d = await clearRes.json().catch(() => ({}))
          throw new Error(d.error || 'Failed to clear products')
        }
      }
      let totalCreated = 0
      const allErrors: string[] = []
      for (let i = 0; i < sortedPages.length; i++) {
        const { page_number } = sortedPages[i]
        setBuildByPageProgress((p) => (p ? { ...p, current: i + 1 } : null))
        const res = await fetch(`/api/catalogs/${selectedId}/build-product-listing/page/${page_number}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ replace: buildReplaceExisting }),
        })
        const data = await res.json()
        totalCreated += data.created ?? 0
        if (data.errors?.length) allErrors.push(...(data.errors as string[]))
        if (!res.ok && data.error) allErrors.push(`Page ${page_number}: ${data.error}`)
      }
      setBuildListingResult({ created: totalCreated, pages_processed: sortedPages.length, errors: allErrors })
      setBuildByPageProgress(null)
      loadCatalogData(selectedId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build by page failed')
      setBuildByPageProgress(null)
    } finally {
      setBuildListingLoading(false)
    }
  }

  const openAssignModal = (pageNumber: number, imageIndex: number, imageUrl: string) => {
    const existing = products.find((p) =>
      (p.images ?? []).some((im: { page_number: number; image_index: number }) => im.page_number === pageNumber && im.image_index === imageIndex)
    )
    if (existing) {
      setAssignPartNumber(existing.manufacturer_part_number ?? '')
      setAssignProductName(existing.product_name ?? '')
      setAssignDescription(existing.description ?? '')
      setAssignSecondaryDescription(existing.secondary_description ?? '')
      setAssignCategory(existing.category ?? '')
    } else {
      setAssignPartNumber('')
      setAssignProductName('')
      setAssignDescription('')
      setAssignSecondaryDescription('')
      setAssignCategory('')
    }
    setAssigningImage({ pageNumber, imageIndex, imageUrl })
  }

  const handleAssignImageToPartNumber = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedId || !assigningImage || !assignPartNumber.trim()) return
    setAssignSubmitting(true)
    setError(null)
    try {
      const res = await fetch(`/api/catalogs/${selectedId}/assign-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          page_number: assigningImage.pageNumber,
          image_index: assigningImage.imageIndex,
          part_number: assignPartNumber.trim(),
          product_name: assignProductName.trim() || undefined,
          description: assignDescription.trim() || undefined,
          secondary_description: assignSecondaryDescription.trim() || undefined,
          category: assignCategory.trim() || undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Failed to assign part number to image')
      setAssigningImage(null)
      setAssignPartNumber('')
      setAssignProductName('')
      setAssignDescription('')
      setAssignSecondaryDescription('')
      setAssignCategory('')
      loadCatalogData(selectedId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to assign part number to image')
    } finally {
      setAssignSubmitting(false)
    }
  }

  const pages = content?.pages ?? []
  const sortedPages = [...pages].sort((a, b) => a.page_number - b.page_number)
  const contentTotalPages = Math.max(1, Math.ceil(sortedPages.length / contentPageSize))
  const contentPagesSlice = sortedPages.slice(
    (contentPage - 1) * contentPageSize,
    contentPage * contentPageSize
  )
  const productsTotalPages = Math.max(1, Math.ceil(products.length / productsPageSize))
  const productsSlice = products.slice(
    (productsPage - 1) * productsPageSize,
    productsPage * productsPageSize
  )

  return (
    <div className="min-h-screen bg-stone-50 text-stone-900">
      <header className="border-b border-stone-200 bg-white px-4 py-3 flex items-center gap-4">
        <Link href="/" className="text-indigo-600 hover:underline font-medium">← Chat</Link>
        <h1 className="text-xl font-semibold">Catalog setup</h1>
      </header>

      <main className="max-w-5xl mx-auto p-4">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <label className="font-medium">Catalog</label>
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="border border-stone-300 rounded px-3 py-2 bg-white min-w-[200px]"
          >
            <option value="">Select a catalog</option>
            {catalogs.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          {content && (
            <span className="text-stone-500 text-sm">
              {content.catalog_name} · {sortedPages.length} page(s)
            </span>
          )}
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-800 text-sm">
            {error}
          </div>
        )}

        {loading && <p className="text-stone-500">Loading…</p>}

        {!loading && selectedId && content && (
          <>
            <div className="flex gap-2 border-b border-stone-200 mb-4">
              {(['content', 'profile', 'products'] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 rounded-t font-medium ${activeTab === tab ? 'bg-white border border-b-0 border-stone-200 -mb-px' : 'text-stone-600 hover:bg-stone-100'}`}
                >
                  {tab === 'content' && 'Content'}
                  {tab === 'profile' && 'Profile'}
                  {tab === 'products' && 'Products'}
                </button>
              ))}
            </div>

            {activeTab === 'content' && (
              <section className="space-y-4">
                <p className="text-sm text-stone-600">
                  Review pages, chunks, and images. Click an image and <strong>Assign part number</strong> to link that image to a product.
                </p>
                {sortedPages.length > contentPageSize && (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="text-stone-600">Pages {(contentPage - 1) * contentPageSize + 1}–{Math.min(contentPage * contentPageSize, sortedPages.length)} of {sortedPages.length}</span>
                    <button
                      type="button"
                      onClick={() => setContentPage((p) => Math.max(1, p - 1))}
                      disabled={contentPage <= 1}
                      className="px-3 py-1.5 rounded border border-stone-300 bg-white text-stone-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-stone-50"
                    >
                      Previous
                    </button>
                    <span className="text-stone-500">Page {contentPage} of {contentTotalPages}</span>
                    <button
                      type="button"
                      onClick={() => setContentPage((p) => Math.min(contentTotalPages, p + 1))}
                      disabled={contentPage >= contentTotalPages}
                      className="px-3 py-1.5 rounded border border-stone-300 bg-white text-stone-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-stone-50"
                    >
                      Next
                    </button>
                  </div>
                )}
                {contentPagesSlice.map((page) => (
                  <div key={page.page_number} className="border border-stone-200 rounded-lg bg-white overflow-hidden">
                    <div className="px-4 py-2 bg-stone-100 font-medium">
                      Page {page.page_number}
                    </div>
                    <div className="p-4 grid gap-4 md:grid-cols-2">
                      <div>
                        <div className="text-xs font-medium text-stone-500 mb-1">Chunks</div>
                        <div className="space-y-2 max-h-60 overflow-y-auto">
                          {page.chunks.map((c) => (
                            <div key={c.id} className="text-sm p-2 bg-stone-50 rounded border border-stone-100">
                              {c.text.slice(0, 300)}{c.text.length > 300 ? '…' : ''}
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs font-medium text-stone-500 mb-1">Images — click to assign part number</div>
                        <div className="flex flex-wrap gap-2">
                          {page.images.map((img) => {
                            const isAssigning = assigningImage?.pageNumber === page.page_number && assigningImage?.imageIndex === img.image_index
                            return (
                              <div key={img.image_index} className="relative">
                                <a
                                  href={imageSrc(img.url)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="block w-20 h-20 rounded border border-stone-200 overflow-hidden bg-stone-100"
                                >
                                  <img src={imageSrc(img.url)} alt="" className="w-full h-full object-contain" />
                                </a>
                                <button
                                  type="button"
                                  onClick={() => (isAssigning ? setAssigningImage(null) : openAssignModal(page.page_number, img.image_index, imageSrc(img.url)))}
                                  className="mt-1 w-full text-xs px-2 py-1 rounded border border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                                >
                                  {isAssigning ? 'Cancel' : 'Assign part #'}
                                </button>
                              </div>
                            )
                          })}
                          {page.images.length === 0 && <span className="text-stone-400 text-sm">No images</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </section>
            )}

            {activeTab === 'products' && (
              <section className="space-y-6">
                <p className="text-sm text-stone-600">
                  Generate a product listing from the catalog using your profile, or add products manually. Review and correct in the list below; then export.
                </p>
                <div className="border border-stone-200 rounded-lg bg-white p-4">
                  <h3 className="font-medium mb-3">Build product listing from catalog</h3>
                  <p className="text-sm text-stone-600 mb-3">
                    Uses chunk text and your catalog profile to extract products per page (part number, name, description, category). Images are linked to products by zone (when profile uses zone-based association) or by layout. <strong>Build by page</strong> is recommended for large catalogs (avoids timeouts and saves progress after each page).
                  </p>
                  <div className="flex flex-wrap items-center gap-3 mb-4">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={buildReplaceExisting} onChange={(e) => setBuildReplaceExisting(e.target.checked)} className="rounded" />
                      <span className="text-sm"><strong>Replacement mode</strong>: remove existing products (for the page or catalog) before inserting. Uncheck for <strong>Update mode</strong> (add only; may duplicate if run again on same page).</span>
                    </label>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={handleBuildProductListingByPage}
                      disabled={buildListingLoading || !content?.pages?.length}
                      className="px-4 py-2 bg-emerald-600 text-white rounded font-medium hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {buildByPageProgress
                        ? `Building page ${buildByPageProgress.current} of ${buildByPageProgress.total}…`
                        : buildListingLoading
                          ? 'Building…'
                          : 'Build by page (recommended)'}
                    </button>
                    <button
                      type="button"
                      onClick={handleBuildProductListing}
                      disabled={buildListingLoading}
                      className="px-4 py-2 bg-stone-600 text-white rounded font-medium hover:bg-stone-700 disabled:opacity-50"
                    >
                      Build all in one request
                    </button>
                  </div>
                  {buildByPageProgress && (
                    <p className="mt-2 text-sm text-stone-600">
                      Progress: page {buildByPageProgress.current} of {buildByPageProgress.total} · {buildByPageProgress.created} products so far.
                      <span className="block mt-1 text-stone-500 text-xs">Watch the Flask server terminal for per-step timing (chunks → LLM → DB).</span>
                    </p>
                  )}
                  {buildListingResult && (
                    <div className="mt-3 p-3 rounded bg-stone-50 border border-stone-200 text-sm">
                      Created <strong>{buildListingResult.created}</strong> products from <strong>{buildListingResult.pages_processed}</strong> pages. Review the list below and correct or assign images as needed.
                      {buildListingResult.errors.length > 0 && (
                        <p className="mt-2 text-amber-700">Warnings: {buildListingResult.errors.join('; ')}</p>
                      )}
                    </div>
                  )}
                </div>
                <div className="border border-stone-200 rounded-lg bg-white p-4">
                  <h3 className="font-medium mb-3">Process single page (granular testing)</h3>
                  <p className="text-sm text-stone-600 mb-3">
                    Run the product extraction for one page only. Use this to test your profile before building the full catalog. The <strong>Replacement / Update</strong> setting above applies: Replacement removes existing products for that page first; Update adds without removing (may duplicate if you run again).
                  </p>
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-2">
                      <span className="text-sm font-medium text-stone-700">Page number</span>
                      <input
                        type="number"
                        min={1}
                        value={buildSinglePageNumber}
                        onChange={(e) => setBuildSinglePageNumber(e.target.value)}
                        placeholder="e.g. 1"
                        className="border border-stone-300 rounded px-3 py-2 w-24"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={handleBuildSinglePage}
                      disabled={buildListingLoading || !buildSinglePageNumber.trim()}
                      className="px-4 py-2 bg-indigo-600 text-white rounded font-medium hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {buildListingLoading ? 'Processing…' : 'Process single page'}
                    </button>
                  </div>
                  {buildSinglePageResult && (
                    <div className="mt-3 p-3 rounded bg-stone-50 border border-stone-200 text-sm">
                      Page <strong>{buildSinglePageResult.page_number}</strong>: created <strong>{buildSinglePageResult.created}</strong> products. Review the list below.
                      {buildSinglePageResult.errors.length > 0 && (
                        <p className="mt-2 text-amber-700">Warnings: {buildSinglePageResult.errors.join('; ')}</p>
                      )}
                    </div>
                  )}
                </div>
                <div className="border border-stone-200 rounded-lg bg-white p-4">
                  <h3 className="font-medium mb-3">Add product to database (manual)</h3>
                  <form onSubmit={handleAddProduct} className="space-y-3 grid gap-3 md:grid-cols-2">
                    <div>
                      <label className="block text-sm text-stone-600 mb-1">Part number (required)</label>
                      <input type="text" value={productPartNumber} onChange={(e) => setProductPartNumber(e.target.value)} className="border border-stone-300 rounded px-3 py-2 w-full" placeholder="Manufacturer part number" required />
                    </div>
                    <div>
                      <label className="block text-sm text-stone-600 mb-1">Product name</label>
                      <input type="text" value={productName} onChange={(e) => setProductName(e.target.value)} className="border border-stone-300 rounded px-3 py-2 w-full" placeholder="Product name" />
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-sm text-stone-600 mb-1">Description</label>
                      <textarea value={productDescription} onChange={(e) => setProductDescription(e.target.value)} rows={2} className="border border-stone-300 rounded px-3 py-2 w-full" placeholder="Description" />
                    </div>
                    <div>
                      <label className="block text-sm text-stone-600 mb-1">Secondary description</label>
                      <input type="text" value={productSecondaryDesc} onChange={(e) => setProductSecondaryDesc(e.target.value)} className="border border-stone-300 rounded px-3 py-2 w-full" placeholder="Specs, notes" />
                    </div>
                    <div>
                      <label className="block text-sm text-stone-600 mb-1">Category</label>
                      <input type="text" value={productCategory} onChange={(e) => setProductCategory(e.target.value)} className="border border-stone-300 rounded px-3 py-2 w-full" placeholder="e.g. from PDF page heading" />
                    </div>
                    <div>
                      <label className="block text-sm text-stone-600 mb-1">Page number</label>
                      <input type="number" min={1} value={productPageNumber} onChange={(e) => setProductPageNumber(e.target.value)} className="border border-stone-300 rounded px-3 py-2 w-24" />
                    </div>
                    <div>
                      <label className="block text-sm text-stone-600 mb-1">Manufacturer</label>
                      <input type="text" value={productManufacturer} onChange={(e) => setProductManufacturer(e.target.value)} className="border border-stone-300 rounded px-3 py-2 w-full" placeholder="Brand / catalog" />
                    </div>
                    <div className="md:col-span-2">
                      <button type="submit" disabled={productSubmitting || !productPartNumber.trim()} className="px-4 py-2 bg-indigo-600 text-white rounded font-medium disabled:opacity-50">
                        {productSubmitting ? 'Adding…' : 'Add product'}
                      </button>
                    </div>
                  </form>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => handleExport('json')} className="px-4 py-2 bg-stone-700 text-white rounded font-medium">Export JSON</button>
                  <button type="button" onClick={() => handleExport('csv')} className="px-4 py-2 bg-stone-700 text-white rounded font-medium">Export CSV</button>
                </div>
                <div>
                  <h3 className="font-medium mb-2">Products ({products.length})</h3>
                  {products.length > productsPageSize && (
                    <div className="flex flex-wrap items-center gap-2 text-sm mb-2">
                      <span className="text-stone-600">Showing {(productsPage - 1) * productsPageSize + 1}–{Math.min(productsPage * productsPageSize, products.length)} of {products.length}</span>
                      <button
                        type="button"
                        onClick={() => setProductsPage((p) => Math.max(1, p - 1))}
                        disabled={productsPage <= 1}
                        className="px-3 py-1.5 rounded border border-stone-300 bg-white text-stone-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-stone-50"
                      >
                        Previous
                      </button>
                      <span className="text-stone-500">Page {productsPage} of {productsTotalPages}</span>
                      <button
                        type="button"
                        onClick={() => setProductsPage((p) => Math.min(productsTotalPages, p + 1))}
                        disabled={productsPage >= productsTotalPages}
                        className="px-3 py-1.5 rounded border border-stone-300 bg-white text-stone-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-stone-50"
                      >
                        Next
                      </button>
                    </div>
                  )}
                  <div className="border border-stone-200 rounded-lg overflow-hidden">
                    {products.length === 0 ? (
                      <div className="p-4 text-stone-500 text-sm">No products yet. Use &quot;Build product listing&quot; above to generate from the catalog, or add products manually; then assign images as needed.</div>
                    ) : (
                      <ul className="divide-y divide-stone-100">
                        {productsSlice.map((p) => (
                          <li key={p.id} className="p-4 bg-white">
                            <div className="flex flex-wrap items-start gap-3">
                              <div className="flex-1 min-w-0">
                                <span className="font-mono font-medium text-indigo-700">{p.manufacturer_part_number}</span>
                                {p.product_name && <span className="ml-2 text-stone-700">{p.product_name}</span>}
                                {p.category && <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-stone-200 text-stone-600">{p.category}</span>}
                                {p.page_number != null && <span className="text-stone-500 text-sm ml-2">p.{p.page_number}</span>}
                                {p.description && <p className="text-sm text-stone-600 mt-1 line-clamp-2">{p.description}</p>}
                              </div>
                              <div className="flex items-center gap-2">
                                {(p.images?.length ?? 0) > 0 && (
                                  <div className="flex gap-1">
                                    {(p.images ?? []).map((img: { image_id: number; url: string }) => (
                                      <a key={img.image_id} href={imageSrc(img.url)} target="_blank" rel="noopener noreferrer" className="w-12 h-12 rounded border border-stone-200 overflow-hidden bg-stone-100">
                                        <img src={imageSrc(img.url)} alt="" className="w-full h-full object-contain" />
                                      </a>
                                    ))}
                                  </div>
                                )}
                                <button type="button" onClick={() => setAssignImageForProductId(assignImageForProductId === p.id ? null : p.id)} className="text-sm px-2 py-1 border border-stone-300 rounded text-stone-700 hover:bg-stone-50">
                                  {assignImageForProductId === p.id ? 'Cancel' : 'Assign image'}
                                </button>
                              </div>
                            </div>
                            {assignImageForProductId === p.id && content && (
                              <div className="mt-3 pt-3 border-t border-stone-100">
                                <span className="text-xs text-stone-500 block mb-2">Pick an image from the catalog to link to this product:</span>
                                <div className="flex flex-wrap gap-2">
                                  {sortedPages.map((page) =>
                                    page.images.map((img) => (
                                      <button
                                        key={`${page.page_number}-${img.image_index}`}
                                        type="button"
                                        onClick={() => handleAssignImage(p.id, content.catalog_id, page.page_number, img.image_index)}
                                        className="w-16 h-16 rounded border border-stone-200 overflow-hidden bg-stone-50 hover:border-indigo-400 focus:border-indigo-400"
                                      >
                                        <img src={imageSrc(img.url)} alt="" className="w-full h-full object-contain" />
                                      </button>
                                    ))
                                  )}
                                </div>
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </section>
            )}

            {activeTab === 'profile' && (
              <section className="border border-stone-200 rounded-lg bg-white p-4 space-y-6">
                {/* Profile status and Analyze (Phase 2) */}
                <div className="border-b border-stone-200 pb-4">
                  <h3 className="font-medium text-stone-800 mb-2">Catalog layout profile</h3>
                  <p className="text-sm text-stone-600 mb-3">
                    Run <strong>Analyze Catalog Layout</strong> once per catalog to generate a layout profile (zones, delimiters, image rules) using an advanced model. Use <strong>Rebuild this catalog</strong> to re-ingest only this catalog&apos;s PDF (chunks, images, page blocks) without affecting other catalogs. The profile is used for <strong>Build product listing</strong> and for <strong>LLM extraction instructions</strong> when extracting products.
                  </p>
                  <div className="flex flex-wrap items-center gap-3 mb-3">
                    <span className="text-sm font-medium text-stone-700">
                      Status:{' '}
                      {profileStatus?.status === 'analyzed' && (
                        <span className="text-stone-600">Analyzed{profileStatus.analyzed_at ? ` on ${new Date(profileStatus.analyzed_at).toLocaleDateString()}` : ''}{profileStatus.analyzed_by_model ? ` using ${profileStatus.analyzed_by_model}` : ''}</span>
                      )}
                      {profileStatus?.status === 'verified' && (
                        <span className="text-emerald-700">Verified{profileStatus.analyzed_at ? ` on ${new Date(profileStatus.analyzed_at).toLocaleDateString()}` : ''}</span>
                      )}
                      {(!profileStatus || !profileStatus.status) && <span className="text-amber-700">Not analyzed</span>}
                    </span>
                    <span className="text-sm text-stone-500">
                      Last rebuilt:{' '}
                      {profileStatus?.last_rebuild_at ? new Date(profileStatus.last_rebuild_at).toLocaleString() : 'Never'}
                    </span>
                    {(profileStatus?.status === 'analyzed' || profileStatus?.status === 'verified') && (
                      <button type="button" onClick={handleLoadProfileEditor} className="text-sm px-3 py-1.5 border border-stone-300 rounded font-medium text-stone-700 hover:bg-stone-50">
                        Edit profile (JSON)
                      </button>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="text-sm text-stone-600">
                      Sample pages (optional, comma-separated; leave empty for auto):
                    </label>
                    <input
                      type="text"
                      value={analyzeSamplePages}
                      onChange={(e) => setAnalyzeSamplePages(e.target.value)}
                      placeholder="e.g. 1, 5, 10"
                      className="border border-stone-300 rounded px-3 py-1.5 w-40 font-mono text-sm"
                      disabled={analyzeLoading}
                    />
                    <button
                      type="button"
                      onClick={handleAnalyzeCatalog}
                      disabled={analyzeLoading}
                      className="px-4 py-2 bg-indigo-600 text-white rounded font-medium hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {analyzeLoading ? 'Analyzing… (15–30 s)' : 'Analyze Catalog Layout'}
                    </button>
                    <button
                      type="button"
                      onClick={handleRebuildCatalog}
                      disabled={rebuildLoading}
                      className="px-4 py-2 bg-stone-700 text-white rounded font-medium hover:bg-stone-800 disabled:opacity-50"
                    >
                      {rebuildLoading ? 'Rebuilding…' : 'Rebuild this catalog'}
                    </button>
                  </div>
                  {rebuildError && <p className="mt-2 text-sm text-red-600">{rebuildError}</p>}
                  {analyzeError && <p className="mt-2 text-sm text-red-600">{analyzeError}</p>}
                  {analyzeResult?.summary && (
                    <div className="mt-3 p-3 rounded bg-stone-50 border border-stone-200 text-sm">
                      <span className="font-medium">Summary: </span>
                      Zone method: {analyzeResult.summary.zone_detection ?? '—'}; Catalog number patterns: {analyzeResult.summary.catalog_number_patterns_count ?? 0}.
                      {analyzeResult.summary.low_confidence?.length ? (
                        <span className="block mt-1 text-amber-700">Review manually: {analyzeResult.summary.low_confidence.join(', ')} (confidence &lt; 7)</span>
                      ) : null}
                    </div>
                  )}
                  {analyzeResult?.validation_report && analyzeResult.validation_report.length > 0 && (
                    <details className="mt-3 p-3 rounded bg-slate-50 border border-slate-200 text-sm">
                      <summary className="font-medium cursor-pointer text-slate-800">Validation report (sample pages)</summary>
                      <div className="mt-2 space-y-3">
                        {analyzeResult.validation_report.map(({ page_number, report }) => (
                          <div key={page_number} className="pl-2 border-l-2 border-slate-300">
                            <span className="font-medium text-slate-700">Page {page_number}</span>
                            <span className="ml-2 text-slate-600">zones: {report.zones_count}</span>
                            {report.per_zone.map((zone: ValidationZone) => (
                              <div key={zone.zone_index} className="mt-1 ml-2 text-slate-600">
                                Zone {zone.zone_index}: {zone.columns_count} column(s)
                                {zone.columns?.filter(Boolean).map((col: { family_name: string; mpns: string[]; product_count: number } | null, i: number) => col && (
                                  <div key={i} className="ml-2">— {col.family_name || '—'} ({col.product_count} products: {col.mpns?.slice(0, 3).join(', ')}{col.mpns?.length > 3 ? '…' : ''})</div>
                                ))}
                                {zone.images?.length ? (
                                  <div className="ml-2 text-slate-500">{zone.images.length} image(s): {zone.images.map((im: { width_pt: number; height_pt: number; association: string; assigned_to: string | null }, i: number) => (
                                    <span key={i}>{im.width_pt}×{im.height_pt}pt → {im.association === 'large_family' ? 'family' : im.assigned_to ?? '—'}{i < zone.images.length - 1 ? '; ' : ''}</span>
                                  ))}</div>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>

                {/* Edit profile JSON (when opened) */}
                {showProfileEditor && (
                  <div className="border border-stone-200 rounded-lg p-4 bg-stone-50">
                    <h3 className="font-medium text-stone-800 mb-2">Profile JSON</h3>
                    <textarea
                      value={profileAnalysisJson}
                      onChange={(e) => { setProfileAnalysisJson(e.target.value); setProfileAnalysisDirty(true); }}
                      rows={16}
                      className="font-mono text-sm border border-stone-300 rounded px-3 py-2 w-full"
                      spellCheck={false}
                    />
                    <div className="flex items-center gap-3 mt-2">
                      <button
                        type="button"
                        onClick={handleSaveProfileAnalysis}
                        disabled={!profileAnalysisDirty || profileAnalysisSaving}
                        className="px-4 py-2 bg-indigo-600 text-white rounded font-medium disabled:opacity-50"
                      >
                        {profileAnalysisSaving ? 'Saving…' : 'Save (set Verified)'}
                      </button>
                      <button type="button" onClick={() => { setShowProfileEditor(false); setProfileAnalysisDirty(false); }} className="px-4 py-2 border border-stone-300 rounded font-medium text-stone-700 hover:bg-stone-100">
                        Close
                      </button>
                      {profileAnalysisDirty && <span className="text-amber-600 text-sm">Unsaved changes</span>}
                    </div>
                  </div>
                )}

              </section>
            )}
          </>
        )}

        {!loading && !selectedId && catalogs.length === 0 && (
          <p className="text-stone-500">No catalogs found. Run a rebuild to load PDFs from <code className="bg-stone-200 px-1 rounded">scripts/source_files/</code>.</p>
        )}
      </main>

      {/* Modal: Assign product attributes to image (generates sample data) */}
      {assigningImage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onClick={() => setAssigningImage(null)} role="dialog" aria-modal="true" aria-labelledby="assign-product-title">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="p-5 border-b border-stone-200 flex items-center justify-between">
              <h2 id="assign-product-title" className="text-lg font-semibold text-stone-900">Assign product to image</h2>
              <button type="button" onClick={() => setAssigningImage(null)} className="p-1 rounded text-stone-500 hover:bg-stone-100 hover:text-stone-700" aria-label="Close">
                <span className="text-xl leading-none">×</span>
              </button>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-sm text-stone-600">
                Page {assigningImage.pageNumber}, image {assigningImage.imageIndex}. Assign item attributes to generate sample data for this catalog.
              </p>
              {assigningImage.imageUrl && (
                <div className="flex justify-center">
                  <img src={assigningImage.imageUrl} alt="" className="w-32 h-32 object-contain rounded border border-stone-200 bg-stone-50" />
                </div>
              )}
              <form onSubmit={handleAssignImageToPartNumber} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-1">Part number (required)</label>
                  <input
                    type="text"
                    value={assignPartNumber}
                    onChange={(e) => setAssignPartNumber(e.target.value)}
                    className="border border-stone-300 rounded-lg px-3 py-2 w-full"
                    placeholder="e.g. ABC-123"
                    required
                    autoFocus
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-1">Product name (optional)</label>
                  <input
                    type="text"
                    value={assignProductName}
                    onChange={(e) => setAssignProductName(e.target.value)}
                    className="border border-stone-300 rounded-lg px-3 py-2 w-full"
                    placeholder="Product name"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-1">Description (optional)</label>
                  <textarea
                    value={assignDescription}
                    onChange={(e) => setAssignDescription(e.target.value)}
                    rows={3}
                    className="border border-stone-300 rounded-lg px-3 py-2 w-full resize-none"
                    placeholder="Main description"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-1">Secondary description (optional)</label>
                  <textarea
                    value={assignSecondaryDescription}
                    onChange={(e) => setAssignSecondaryDescription(e.target.value)}
                    rows={2}
                    className="border border-stone-300 rounded-lg px-3 py-2 w-full resize-none"
                    placeholder="Specs, features, or additional notes"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-stone-700 mb-1">Category (optional)</label>
                  <input
                    type="text"
                    value={assignCategory}
                    onChange={(e) => setAssignCategory(e.target.value)}
                    className="border border-stone-300 rounded-lg px-3 py-2 w-full"
                    placeholder="e.g. from PDF page heading"
                  />
                </div>
                <div className="flex gap-3 pt-2">
                  <button type="button" onClick={() => setAssigningImage(null)} className="flex-1 px-4 py-2 border border-stone-300 rounded-lg font-medium text-stone-700 hover:bg-stone-50">
                    Cancel
                  </button>
                  <button type="submit" disabled={assignSubmitting || !assignPartNumber.trim()} className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:pointer-events-none">
                    {assignSubmitting ? 'Saving…' : 'Save & add sample'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
