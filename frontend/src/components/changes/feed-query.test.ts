import { describe, expect, it, vi } from 'vitest';

import {
  changeFeedRequest,
  clearFilterParams,
  commentFeedRequest,
  dayParam,
  hasChangeFilters,
  hasCommentFilters,
  listParam,
  withListParam,
  withParam,
  withStateParam,
} from './feed-query';

describe('Recent changes URL state', () => {
  it('reads and writes comma-separated list filters and returns to page 1', () => {
    const search = { entity_type: 'project,comment', page: '3', page_size: '100' };
    expect(listParam(search, 'entity_type')).toEqual(['project', 'comment']);
    expect(listParam(search, 'channel')).toEqual([]);
    expect(withListParam(search, 'channel', ['ui', 'seed'])).toEqual({
      entity_type: 'project,comment',
      channel: 'ui,seed',
      page_size: '100',
    });
    expect(withListParam(search, 'entity_type', [])).toEqual({ page_size: '100' });
    expect(withParam(search, 'batch_id', '')).toEqual({ entity_type: 'project,comment', page_size: '100' });
  });

  it('sets and removes a page-state parameter without leaving the page', () => {
    const search = { kind: 'update_field', page: '2', page_size: '5' };
    const expanded = withStateParam(search, 'proposal', 'prp_A');
    expect(expanded).toEqual({ kind: 'update_field', page: '2', page_size: '5', proposal: 'prp_A' });
    expect(withStateParam(expanded, 'proposal', null)).toEqual(search);
    expect(withStateParam(expanded, 'proposal', '')).toEqual(search);
  });

  it('sends local days as inclusive timestamps and drops invalid days', () => {
    vi.stubEnv('TZ', 'Europe/Kyiv');
    const search = { since: '2026-10-01', until: '2026-10-02', channel: 'ui', page: '2', unknown: 'x' };
    expect(changeFeedRequest(search)).toEqual({
      since: '2026-09-30T21:00:00.000000Z',
      until: '2026-10-02T20:59:59.999999Z',
      channel: 'ui',
      page: '2',
    });
    expect(changeFeedRequest({ since: '2026-02-30', until: '2026-10-02T00:00:00Z' })).toEqual({});
    expect(dayParam({ since: '2026-10-01' }, 'since')).toBe('2026-10-01');
    expect(dayParam({ until: 'yesterday' }, 'until')).toBeNull();
  });

  it('knows whether filters are active and clears them but keeps the page size', () => {
    expect(hasChangeFilters({ page: '2', page_size: '25' })).toBe(false);
    expect(hasChangeFilters({ batch_id: 'b1' })).toBe(true);
    expect(clearFilterParams({ action: 'update', since: '2026-10-01', page: '4', page_size: '25' })).toEqual({
      page_size: '25',
    });
  });
});

describe('Comments page URL state', () => {
  it('requests exactly the URL filters and paging', () => {
    const search = { status: 'open', entity_type: 'project', q: 'example', deleted: 'include', page: '2', comments: 'x' };
    expect(commentFeedRequest(search)).toEqual({
      status: 'open',
      entity_type: 'project',
      q: 'example',
      deleted: 'include',
      page: '2',
    });
    expect(hasCommentFilters({ page_size: '25' })).toBe(false);
    expect(hasCommentFilters({ q: 'example' })).toBe(true);
  });
});
