// Field choices for comments (docs/UI.md §4.3): a comment refers to the whole
// record or to one registry field of the subject type (derived included).
import type { ComboboxItem, ComboboxItemGroup } from '@mantine/core';

import type { EntityType, EntityTypeMeta, Meta } from '../../api/types';
import { detailFieldGroups } from '../detail/field-groups';

/** `field=-` selects entity-level threads only (docs/API.md §3.3). */
export const ENTITY_LEVEL = '-';

export type FieldOptionGroup = ComboboxItemGroup<ComboboxItem, string>;

/** The subject's fields by group; the System group is left out. */
export function commentFieldGroups(meta: Meta, type: EntityType, typeMeta: EntityTypeMeta): FieldOptionGroup[] {
  return detailFieldGroups(meta, type, typeMeta)
    .filter((group) => group.key !== 'system')
    .map((group) => ({
      group: group.label,
      items: group.fields.map((field) => ({ value: field.name, label: field.label })),
    }));
}

export function fieldLabelOf(typeMeta: EntityTypeMeta, field: string | null): string | null {
  if (field === null) return null;
  return typeMeta.fields.find((spec) => spec.name === field)?.label ?? field;
}
