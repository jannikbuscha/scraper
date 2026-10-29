// Exports are downloaded with fetch → Blob → object URL → a[download]
// (docs/UI.md §1.6); no plain link points at /api.
import { fetchApi } from '../api/client';
import type { EntityType } from '../api/types';
import { exportQueryString, type SearchRecord } from './query-string';

export type ExportFormat = 'csv' | 'xlsx';

/** File name from `Content-Disposition` (RFC 6266 `filename*` or `filename`). */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const extended = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (extended?.[1]) {
    try {
      return decodeURIComponent(extended[1].trim());
    } catch {
      // Fall through to the plain parameter.
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]*)"|([^;\s]+))/.exec(header);
  const name = plain?.[1] ?? plain?.[2];
  return name ? name.trim() : null;
}

/** Strips path separators and control characters from a server-provided name. */
export function safeFilename(name: string, fallback: string): string {
  // eslint-disable-next-line no-control-regex -- control characters are removed on purpose
  const cleaned = name.replace(/[\\/\u0000-\u001f\u007f]/g, '_').trim();
  return cleaned === '' || cleaned === '.' || cleaned === '..' ? fallback : cleaned;
}

/** Downloads the current view; resolves with the file name. Errors throw ApiError. */
export async function downloadExport(type: EntityType, search: SearchRecord, format: ExportFormat): Promise<string> {
  const response = await fetchApi(`/api/entities/${type}/export?${exportQueryString(search, format)}`);
  const blob = await response.blob();
  const fallback = `${type}-export.${format}`;
  const filename = safeFilename(filenameFromDisposition(response.headers.get('Content-Disposition')) ?? fallback, fallback);
  saveBlob(blob, filename);
  return filename;
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noopener';
  anchor.style.display = 'none';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoke after the click has been handled by the browser.
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
