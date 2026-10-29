// Fixtures of the E2E suite (docs/UI.md §7).
//
// - Every scenario fails on an uncaught error in the page.
// - `api` sets up and checks data through the HTTP API.
//
// All texts the scenarios write are synthetic; the seeded projects come from
// seed/projects.yaml.
import { expect, test as base, type APIRequestContext } from '@playwright/test';

export { expect };

// ---------------------------------------------------------------------------
// API client (docs/API.md)
// ---------------------------------------------------------------------------

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

export interface Item {
  id: string;
  type: string;
  label: string;
  version: number;
  fields: Record<string, Json>;
  virtual: Record<string, Json>;
}

interface Revision {
  version: number;
  channel: string;
  note: string | null;
  action: string;
  changed_fields: string[];
}

export class Api {
  readonly #request: APIRequestContext;

  constructor(request: APIRequestContext) {
    this.#request = request;
  }

  async get<T>(path: string): Promise<T> {
    const response = await this.#request.get(path);
    expect(response.status(), `GET ${path}: ${await response.text()}`).toBe(200);
    return (await response.json()) as T;
  }

  async write<T>(method: 'POST' | 'PATCH', path: string, body: Json): Promise<T> {
    const response = await this.#request.fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify(body),
    });
    expect(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`).toBe(true);
    return (await response.json()) as T;
  }

  /** A seeded project by its slug. */
  async project(slug: string): Promise<Item> {
    const list = await this.get<{ items: Item[] }>(`/api/entities/project?f.slug=eq:${encodeURIComponent(slug)}`);
    const [item] = list.items;
    if (!item) throw new Error(`No project with the slug ${slug}`);
    return item;
  }

  async item(type: string, id: string): Promise<Item> {
    return (await this.get<{ item: Item }>(`/api/entities/${type}/${id}`)).item;
  }

  async patch(type: string, id: string, changes: Record<string, Json>, note: string | null): Promise<Item> {
    return (await this.write<{ item: Item }>('PATCH', `/api/entities/${type}/${id}`, { changes, note })).item;
  }

  /** The record's revisions, newest first. */
  async revisions(type: string, id: string): Promise<Revision[]> {
    return (await this.get<{ items: Revision[] }>(`/api/entities/${type}/${id}/revisions?page_size=100`)).items;
  }
}

/** A unique suffix for synthetic texts, so repeated runs on one database stay distinguishable. */
export const uniqueSuffix = (): string => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

interface Fixtures {
  /** Collected uncaught errors; checked when the test ends. */
  problems: string[];
  api: Api;
}

export const test = base.extend<Fixtures>({
  problems: [
    // eslint-disable-next-line no-empty-pattern -- Playwright reads the fixtures a fixture needs from this pattern
    async ({}, provide) => {
      const problems: string[] = [];
      await provide(problems);
      expect(problems, 'uncaught errors in the browser').toEqual([]);
    },
    { auto: true },
  ],
  context: async ({ context, problems }, provide) => {
    context.on('weberror', (webError) => {
      problems.push(`Uncaught error: ${webError.error().message}`);
    });
    await provide(context);
  },
  api: async ({ request }, provide) => {
    await provide(new Api(request));
  },
});
