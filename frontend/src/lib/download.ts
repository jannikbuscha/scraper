// Exports are downloaded with fetch → Blob → object URL → a[download]
// (docs/UI.md §1.6), so a refused export shows the server's error message.
import { fetchApi } from '../api/client';
import type { EntityType } from '../api/types';
import { exportQueryString, type SearchRecord } from './query-string';

export type ExportFormat = 'csv' | 'xlsx';

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
  const response = await fetchApi(`/api/entities/${type}/export?${exportQueryString(search, format, columns)}`);
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `${type}-export.${format}`;
  saveBlob(blob, filename);
  return filename;
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
