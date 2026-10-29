// Entity types, ID prefixes (docs/DATA_MODEL.md §3) and their UI routes.
import { TABLE_ENTITY_TYPES, type RecordType, type TableEntityType } from '../api/types';

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

/** Path of a detail page, for window.open (middle-click, ctrl-click). */
export const detailHref = (type: TableEntityType, id: string): string =>
  `${TABLE_PATHS[type]}/${encodeURIComponent(id)}`;
