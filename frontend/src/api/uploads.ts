// Raw-body uploads (docs/API.md §7.7, docs/UI.md §8.6): the file itself is the
// request body (no multipart, no JSON) and its name goes into the query. The
// server stores it as an upload snapshot, used by manual documents and imports.
import { useMutation } from '@tanstack/react-query';

import type { UploadResponse } from './acquisition-types';
import { sendRequest } from './client';

/** POST /api/uploads?filename=<name> with the File as the body. */
export async function uploadFile(file: File): Promise<UploadResponse> {
  const query = new URLSearchParams({ filename: file.name });
  const response = await sendRequest(`/api/uploads?${query.toString()}`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: file,
  });
  return (await response.json()) as UploadResponse;
}

/** An upload changes no curated data, so nothing is invalidated. */
export function useUpload() {
  return useMutation({ mutationFn: uploadFile });
}
