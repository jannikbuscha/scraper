// The field choices of a merge (docs/UI.md §8.7, docs/API.md §7.6): per
// differing field the survivor's value (default), the merged record's, or the
// union of both lists.
import type { MergeChoice, MergePreviewField } from '../../api/acquisition-types';

/** The choices a field offers: union only for list fields. */
export const choicesOf = (field: Pick<MergePreviewField, 'list'>): MergeChoice[] =>
  field.list ? ['survivor', 'merged', 'union'] : ['survivor', 'merged'];

/** `fields` of the merge request: every previewed field with the chosen (or default) value. */
export function buildMergeFields(
  preview: readonly MergePreviewField[],
  chosen: Readonly<Record<string, MergeChoice>>,
): Record<string, MergeChoice> {
  return Object.fromEntries(
    preview.map((field) => {
      const choice = chosen[field.name];
      return [field.name, choice && choicesOf(field).includes(choice) ? choice : field.default];
    }),
  );
}

export const CHOICE_LABELS: Record<MergeChoice, string> = {
  survivor: 'Keep',
  merged: 'Take other',
  union: 'Both',
};
