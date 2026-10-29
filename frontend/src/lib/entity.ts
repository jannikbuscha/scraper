// Entity types, ID prefixes (docs/DATA_MODEL.md §3) and their UI routes.
import { TABLE_ENTITY_TYPES, type EntityType, type RecordType, type TableEntityType } from '../api/types';

const ID_PREFIXES: Readonly<Record<string, RecordType>> = {
  prj: 'project',
  svc: 'service',
  evt: 'event',
  doc: 'document',
  org: 'organization',
  par: 'participation',
  cmp: 'component',
  rel: 'relation',
  ind: 'indicator',
  evd: 'evidence',
  voc: 'vocabulary_term',
  view: 'saved_view',
  cmt: 'comment',
};

/** The record type encoded in a prefixed ID, e.g. `svc_01J…` → `service`. */
export function typeFromId(id: string): RecordType | null {
  const separator = id.indexOf('_');
  if (separator <= 0) return null;
  return ID_PREFIXES[id.slice(0, separator)] ?? null;
}

export const TABLE_PATHS = {
  project: '/projects',
  service: '/services',
  event: '/events',
  document: '/documents',
  organization: '/organizations',
} as const satisfies Record<TableEntityType, string>;

export const DETAIL_PATHS = {
  project: '/projects/$id',
  service: '/services/$id',
  event: '/events/$id',
  document: '/documents/$id',
  organization: '/organizations/$id',
} as const satisfies Record<TableEntityType, string>;

export function isTableType(type: string | null | undefined): type is TableEntityType {
  return TABLE_ENTITY_TYPES.some((candidate) => candidate === type);
}

/**
 * Types without a table that have the generic record page `/records/$id`
 * (docs/UI.md §2): the same detail page (fields, edit, delete and undelete,
 * history with compare and restore, comments) for records that Phase 1
 * creates in the UI (evidence) or that the API accepts writes and comments
 * for. Vocabulary terms live on the Codebook page; comments on their subject's.
 */
export const RECORD_PAGE_TYPES = ['participation', 'component', 'relation', 'indicator', 'evidence', 'saved_view'] as const;
export type RecordPageType = (typeof RECORD_PAGE_TYPES)[number];

export function isRecordPageType(type: string | null | undefined): type is RecordPageType {
  return RECORD_PAGE_TYPES.some((candidate) => candidate === type);
}

/** Types with a detail page: the table types and the record-page types. */
export type DetailEntityType = TableEntityType | RecordPageType;

export const hasDetailPage = (type: string | null | undefined): type is DetailEntityType =>
  isTableType(type) || isRecordPageType(type);

/** The route of the generic record page. */
export const RECORD_PATH = '/records/$id';

/** Path of a detail page, for window.open (middle-click, ctrl-click) and copied links. */
export const detailHref = (type: DetailEntityType, id: string): string =>
  isTableType(type) ? `${TABLE_PATHS[type]}/${encodeURIComponent(id)}` : `/records/${encodeURIComponent(id)}`;

/** Narrows an entity type to one with a detail page (null for vocabulary terms). */
export const detailType = (type: EntityType): DetailEntityType | null => (hasDetailPage(type) ? type : null);
