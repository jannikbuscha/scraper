// The inline form of edit mode (docs/UI.md §4.1): an input per editable field
// in the detail page's field groups; read-only fields are shown as values.
import { Input, Stack } from '@mantine/core';
import type { ReactNode } from 'react';

import { useEntityList } from '../../api/queries';
import type {
  EntityTypeMeta,
  FieldSpec,
  Item,
  JsonObject,
  JsonValue,
  Meta,
  Refs,
} from '../../api/types';
import type { DetailEntityType } from '../../lib/entity';
import { asString, asStringArray } from '../../lib/format';
import { canonicalQuery } from '../../lib/query-string';
import { FieldInput, FieldLabel } from '../fields/FieldInput';
import { FieldValue } from '../fields/FieldValue';
import { detailFieldGroups } from './field-groups';
import { serviceSubtree } from './edit-session';
import { FieldGroupSection } from './FieldGroupSection';

/**
 * The parent-service picker offers services of the same project only and
 * never the service itself or its descendants (docs/UI.md §4.1).
 */
function useParentServicePicker(type: DetailEntityType, item: Item, projectId: string | null) {
  const enabled = type === 'service' && projectId !== null;
  const services = useEntityList(
    'service',
    canonicalQuery({ 'f.project_id': `in:${projectId ?? ''}`, page_size: '500' }),
    { enabled },
  );
  if (!enabled) return { lookupFilters: undefined, excludeIds: [item.id] };
  return {
    lookupFilters: { 'f.project_id': `in:${projectId}` },
    excludeIds: serviceSubtree(item.id, services.data?.items ?? []),
  };
}

/** The item's label of a ref field only while the form still holds that ID. */
const refsOfValue = (refs: Refs, field: string, value: JsonValue): Refs | undefined =>
  refs[field]?.id === value ? refs : undefined;

/** Stored codes stay selectable even if their term is inactive now. */
function keepCodes(field: FieldSpec, base: JsonValue): string[] {
  if (field.type === 'vocab') {
    const code = asString(base);
    return code ? [code] : [];
  }
  return field.type === 'vocab_list' ? asStringArray(base) : [];
}

interface EditFieldsProps {
  type: DetailEntityType;
  item: Item;
  meta: Meta;
  typeMeta: EntityTypeMeta;
  editable: ReadonlySet<string>;
  values: JsonObject;
  baseFields: JsonObject;
  errors: Readonly<Record<string, ReactNode>>;
  /** Fields that must be filled although the registry does not require them (e.g. a new scope note). */
  alsoRequired: ReadonlySet<string>;
  onChange: (field: string, value: JsonValue) => void;
}

export function EditFields({
  type,
  item,
  meta,
  typeMeta,
  editable,
  values,
  baseFields,
  errors,
  alsoRequired,
  onChange,
}: EditFieldsProps) {
  const parentPicker = useParentServicePicker(type, item, asString(values.project_id ?? null));
  return (
    <Stack gap="lg">
      {detailFieldGroups(meta, type, typeMeta).map((group) => (
        <FieldGroupSection key={group.key} group={group}>
          <Stack gap="sm">
            {group.fields.map((field) =>
              editable.has(field.name) ? (
                <FieldInput
                  key={field.name}
                  field={field}
                  value={values[field.name] ?? null}
                  required={field.required || alsoRequired.has(field.name)}
                  error={errors[field.name]}
                  refs={refsOfValue(item.refs, field.name, values[field.name] ?? null)}
                  keepCodes={keepCodes(field, baseFields[field.name] ?? null)}
                  {...(field.name === 'parent_service_id' ? parentPicker : {})}
                  onChange={(value) => {
                    onChange(field.name, value);
                  }}
                />
              ) : (
                <Input.Wrapper key={field.name} label={<FieldLabel field={field} />} description="Read-only">
                  <div>
                    <FieldValue field={field} item={item} variant="full" />
                  </div>
                </Input.Wrapper>
              ),
            )}
          </Stack>
        </FieldGroupSection>
      ))}
    </Stack>
  );
}
