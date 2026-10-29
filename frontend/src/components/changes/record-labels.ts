// Labels for record types, channels, actions and fields in feeds, histories
// and the trash. Entity types and their fields are described by GET /api/meta;
// comments have no registry entry, so their tracked fields (docs/DATA_MODEL.md
// §6.6) are labelled here.
import {
  ENTITY_TYPES,
  type Channel,
  type FieldSpec,
  type Meta,
  type RecordType,
  type RevisionAction,
} from '../../api/types';
import { syntheticField } from '../../lib/format';

/** Every type with revisions (docs/API.md §3.4): the entity types and comments. */
export const RECORD_TYPES: readonly RecordType[] = [...ENTITY_TYPES, 'comment'];

const fallbackLabel = (type: string): string => {
  const words = type.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
};

export function recordTypeLabel(meta: Meta | undefined, type: RecordType): string {
  if (type === 'comment') return 'Comment';
  return meta?.entity_types[type]?.label ?? fallbackLabel(type);
}

export function recordTypePlural(meta: Meta | undefined, type: RecordType): string {
  if (type === 'comment') return 'Comments';
  return meta?.entity_types[type]?.label_plural ?? `${fallbackLabel(type)}s`;
}

/** Channel and action codes as shown in the revision badges; changes made in the app are "manual". */
const CHANNEL_LABELS: Record<Channel, string> = {
  ui: 'manual',
  restore: 'restore',
  seed: 'seed',
  import: 'import',
  collector: 'collector',
  merge: 'merge',
  system: 'system',
};

export const channelLabel = (channel: Channel): string => CHANNEL_LABELS[channel];

const ACTION_LABELS: Record<RevisionAction, string> = {
  create: 'create',
  update: 'update',
  verify: 'verify',
  delete: 'delete',
  undelete: 'undelete',
  restore: 'restore',
  merge: 'merge',
  resolve: 'resolve',
  reopen: 'reopen',
};

const options = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }));

export const CHANNEL_OPTIONS = options(CHANNEL_LABELS);
export const ACTION_OPTIONS = options(ACTION_LABELS);

/** The tracked fields of a comment, for diffs and changed-field chips. */
const COMMENT_FIELDS: readonly FieldSpec[] = [
  syntheticField('body_md', 'text', 'Text'),
  syntheticField('status', 'string', 'Status'),
  syntheticField('resolved_at', 'datetime', 'Resolved at'),
];

/** Registry fields of a record type (comments: their tracked fields). */
export function recordFields(meta: Meta | undefined, type: RecordType): readonly FieldSpec[] {
  if (type === 'comment') return COMMENT_FIELDS;
  return meta?.entity_types[type]?.fields ?? [];
}

/** Field labels by name, for changed-field chips. */
export function recordFieldLabels(meta: Meta | undefined, type: RecordType): Record<string, string> {
  return Object.fromEntries(recordFields(meta, type).map((field) => [field.name, field.label]));
}
