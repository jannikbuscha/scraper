// Fixtures of the E2E suite (docs/UI.md §7).
//
// - Every browser context gets the author name in localStorage (option
//   `author`; null leaves it unset, so the app asks for it).
// - Every scenario fails on a `securitypolicyviolation` event, a CSP console
//   error or an uncaught error in the page, in any of its browser contexts.
// - `api` sets up and checks data through the HTTP API, like a second client.
//
// All names and texts the scenarios write are synthetic; the seeded projects
// come from seed/projects.yaml.
import { expect, test as base, type APIRequestContext, type BrowserContext } from '@playwright/test';

export { expect };

/** Synthetic authors; start-server.mjs offers them in the author picker (TEAM_MEMBERS). */
export const ALICE = 'E2E Alice';
export const BOB = 'E2E Bob';

// Reports violations through the console, where `watch` collects them.
const CSP_REPORTER = `document.addEventListener('securitypolicyviolation', (event) => {
  const blocked = event.blockedURI || 'inline';
  console.error('[e2e] securitypolicyviolation: ' + event.violatedDirective + ' blocked ' + blocked);
}, true);`;
const CSP_CONSOLE_MESSAGE = /securitypolicyviolation|Content[ -]Security[ -]Policy/i;

/**
 * Stores the author like the author modal does (docs/UI.md §1.5), unless a
 * name is stored already. The initial about:blank page has no storage.
 */
const authorScript = (author: string): string => `
if (window.location.protocol === 'http:' && window.localStorage.getItem('mdt.author') === null) {
  window.localStorage.setItem('mdt.author', ${JSON.stringify(author)});
}`;

async function watch(context: BrowserContext, author: string | null, problems: string[]): Promise<void> {
  await context.addInitScript({ content: author === null ? CSP_REPORTER : CSP_REPORTER + authorScript(author) });
  context.on('console', (message) => {
    if (message.type() === 'error' && CSP_CONSOLE_MESSAGE.test(message.text())) {
      problems.push(`CSP: ${message.text()}`);
    }
  });
  context.on('weberror', (webError) => {
    problems.push(`Uncaught error: ${webError.error().message}`);
  });
}

// ---------------------------------------------------------------------------
// API client (docs/API.md); writes carry X-Author like the app's.
// ---------------------------------------------------------------------------

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

export interface Item {
  id: string;
  type: string;
  label: string;
  version: number;
  updated_by: string;
  fields: Record<string, Json>;
  virtual: Record<string, Json>;
}

interface Revision {
  version: number;
  author: string;
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
    const response = await this.#request.get(path, { headers: { 'X-Requested-With': 'mdt' } });
    expect(response.status(), `GET ${path}: ${await response.text()}`).toBe(200);
    return (await response.json()) as T;
  }

  async write<T>(method: 'POST' | 'PATCH', path: string, body: Json, author = ALICE): Promise<T> {
    const response = await this.#request.fetch(path, {
      method,
      headers: {
        'X-Requested-With': 'mdt',
        'X-Author': encodeURIComponent(author),
        'Content-Type': 'application/json',
      },
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

  /** PATCH against the current version, as another team member would. */
  async patch(
    type: string,
    id: string,
    changes: Record<string, Json>,
    note: string | null,
    author = ALICE,
  ): Promise<Item> {
    const current = await this.item(type, id);
    const body = { expected_version: current.version, changes, note };
    return (await this.write<{ item: Item }>('PATCH', `/api/entities/${type}/${id}`, body, author)).item;
  }

  /** The record's revisions, newest first. */
  async revisions(type: string, id: string): Promise<Revision[]> {
    return (await this.get<{ items: Revision[] }>(`/api/entities/${type}/${id}/revisions?page_size=100`)).items;
  }
}

/** A unique suffix for synthetic texts, so repeated runs on one database stay distinguishable. */
export const uniqueSuffix = (): string => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

interface Options {
  /** Author name stored in every browser context; null: none (the app asks). */
  author: string | null;
}

interface Fixtures {
  /** Collected CSP violations and uncaught errors; checked when the test ends. */
  problems: string[];
  /** Opens another browser context ("another team member") with the same checks. */
  openContext: (author: string | null) => Promise<BrowserContext>;
  api: Api;
}

export const test = base.extend<Options & Fixtures>({
  author: [ALICE, { option: true }],
  problems: [
    // eslint-disable-next-line no-empty-pattern -- Playwright reads the fixtures a fixture needs from this pattern
    async ({}, provide) => {
      const problems: string[] = [];
      await provide(problems);
      expect(problems, 'CSP violations or uncaught errors in the browser').toEqual([]);
    },
    { auto: true },
  ],
  context: async ({ context, author, problems }, provide) => {
    await watch(context, author, problems);
    await provide(context);
  },
  openContext: async ({ browser, baseURL, viewport, locale, problems }, provide) => {
    const contexts: BrowserContext[] = [];
    await provide(async (author) => {
      const context = await browser.newContext({ baseURL, viewport, locale });
      contexts.push(context);
      await watch(context, author, problems);
      return context;
    });
    await Promise.all(contexts.map((context) => context.close()));
  },
  api: async ({ request }, provide) => {
    await provide(new Api(request));
  },
});
