// Field groups of the detail page in the order of `meta.groups` (docs/UI.md
// §4.1). Layout preferences only: the comment counters are shown by the
// comments panel and a document's extracted text by its own panel.
import type { EntityType, EntityTypeMeta, FieldGroup, FieldSpec, Meta } from '../../api/types';

export interface FieldGroupView {
  key: FieldGroup;
  label: string;
  fields: FieldSpec[];
}

const SHOWN_BY_COMMENTS_PANEL: ReadonlySet<string> = new Set(['open_comments', 'comment_count']);

/** The document's extracted text (`fields.text`, detail responses only). */
export const DOCUMENT_TEXT_FIELD = 'text';

function isRowField(type: EntityType, field: FieldSpec): boolean {
  if (SHOWN_BY_COMMENTS_PANEL.has(field.name) && field.virtual) return false;
  return !(type === 'document' && field.name === DOCUMENT_TEXT_FIELD);
}

export function detailFieldGroups(meta: Meta, type: EntityType, typeMeta: EntityTypeMeta): FieldGroupView[] {
  const fields = typeMeta.fields.filter((field) => isRowField(type, field));
  const known = meta.groups.map((group) => group.key);
  // Groups the server lists, then any group it does not describe (defensive).
  const extra = [...new Set(fields.map((field) => field.group))].filter((key) => !known.includes(key));
  const labels = new Map<FieldGroup, string>(meta.groups.map((group) => [group.key, group.label]));
  return [...known, ...extra]
    .map((key) => ({ key, label: labels.get(key) ?? key, fields: fields.filter((field) => field.group === key) }))
    .filter((group) => group.fields.length > 0);
}

/** Registry labels by field name (changed-field chips, conflict and history views). */
export const fieldLabels = (typeMeta: EntityTypeMeta): Record<string, string> =>
  Object.fromEntries(typeMeta.fields.map((field) => [field.name, field.label]));
