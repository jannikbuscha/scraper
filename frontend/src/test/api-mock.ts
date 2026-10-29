// A fetch stub for component tests: a handler maps request URLs to JSON
// bodies; unknown URLs answer 404 in the API's error envelope.
import { vi } from 'vitest';

export type ApiHandler = (url: URL, init: RequestInit | undefined) => unknown;

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function requestUrl(input: RequestInfo | URL): URL {
  if (input instanceof URL) return input;
  return new URL(typeof input === 'string' ? input : input.url, 'http://localhost');
}

/** Stubs the global fetch (vitest's unstubGlobals restores it after each test). */
export function mockApi(handler: ApiHandler) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const body = handler(requestUrl(input), init);
    if (body instanceof Response) return Promise.resolve(body);
    if (body === undefined) return Promise.resolve(json({ error: { code: 'not_found', message: 'Not found' } }, 404));
    return Promise.resolve(json(body));
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** URLs of the requests made so far to `pathname`. */
export function requestsTo(fetchMock: ReturnType<typeof mockApi>, pathname: string): URL[] {
  return callsTo(fetchMock, pathname).map((call) => call.url);
}

/** URL and options of the requests made so far to `pathname`. */
export function callsTo(
  fetchMock: ReturnType<typeof mockApi>,
  pathname: string,
): { url: URL; init: RequestInit | undefined }[] {
  return fetchMock.mock.calls
    .map(([input, init]) => ({ url: requestUrl(input), init }))
    .filter((call) => call.url.pathname === pathname);
}

/** The parsed JSON body of a request (the API client always sends a string). */
export const jsonBody = (init: RequestInit | undefined): unknown =>
  typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
