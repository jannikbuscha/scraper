// Downloads with fetch → Blob → object URL → a[download] (docs/UI.md §1.6), so
// a refused download shows the server's error message instead of navigating
// to it: exports (docs/API.md §5) and raw snapshot bodies (§7.3).
import { fetchApi } from '../api/client';
import type { EntityType } from '../api/types';
import { exportQueryString, type SearchRecord } from './query-string';

export type ExportFormat = 'csv' | 'xlsx';

/**
 * The file name of a `Content-Disposition` header: the UTF-8 name
 * (`filename*=UTF-8''…`, RFC 6266) if present, else the plain one, else `fallback`.
 */
export function filenameFromDisposition(disposition: string | null, fallback: string): string {
  const header = disposition ?? '';
  const extended = /filename\*=UTF-8''([^;]+)/i.exec(header)?.[1];
  if (extended) {
    try {
      return decodeURIComponent(extended.trim());
    } catch {
      // A malformed encoding: use the plain name.
    }
  }
  return /filename="([^"]+)"/.exec(header)?.[1] ?? fallback;
}

/** Downloads `path` (an API GET) and resolves with the file name; errors throw ApiError. */
export async function downloadFrom(path: string, fallbackName: string): Promise<string> {
  const response = await fetchApi(path);
  const blob = await response.blob();
  const filename = filenameFromDisposition(response.headers.get('Content-Disposition'), fallbackName);
  saveBlob(blob, filename);
  return filename;
}

/**
 * Downloads the current view with the table's visible `columns` (the ID is
 * added first); resolves with the file name. Errors throw ApiError.
 */
export async function downloadExport(
  type: EntityType,
  search: SearchRecord,
  format: ExportFormat,
  columns: readonly string[],
): Promise<string> {
  return downloadFrom(`/api/entities/${type}/export?${exportQueryString(search, format, columns)}`, `${type}-export.${format}`);
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoke after the click has been handled by the browser.
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
