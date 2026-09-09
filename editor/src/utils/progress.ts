/*
 * Shared progress normalization and display helpers.
 *
 * Keeps scanner, ingestion pages, and compact top-bar progress at one decimal
 * without fabricating intermediate values in the browser.
 */

/** Clamp a backend percentage and retain one decimal place. */
export function normalizeProgress(value: number): number {
  return Math.round(Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0)) * 10) / 10
}

/** Format a normalized percentage with the product-wide display precision. */
export function formatProgress(value: number): string {
  return normalizeProgress(value).toFixed(1)
}
