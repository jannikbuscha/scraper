// One input per field type (docs/UI.md §4.1), shared by the create modal,
// bulk edit and the detail page's edit mode. Inputs are controlled and emit
// API values (empty text → null, lists → arrays).
import { Input, NumberInput, Switch, Textarea, TextInput } from '@mantine/core';
import { DateInput } from '@mantine/dates';
import type { ReactNode } from 'react';

import type { FieldSpec, JsonValue, Refs } from '../../api/types';
import { fieldValueError, SLUG_HINT } from '../../lib/field-validation';
import { asAliases, asNumber, asString, asStringArray } from '../../lib/format';
import { PARTIAL_DATE_HINT } from '../../lib/partial-date';
import type { SearchRecord } from '../../lib/query-string';
import { HelpTooltip } from '../HelpTooltip';
import { ValueDisplay } from './FieldValue';
import { AliasListInput } from './inputs/AliasListInput';
import { DateTimeUtcInput } from './inputs/DateTimeUtcInput';
import { LineListInput } from './inputs/LineListInput';
import { RefSelect } from './inputs/RefSelect';
import { VocabMultiSelect, VocabSelect } from './inputs/VocabSelect';

export interface FieldInputProps {
  field: FieldSpec;
  value: JsonValue;
  onChange: (value: JsonValue) => void;
  /** An error from the server; otherwise client-side format errors are shown. */
  error?: ReactNode;
  disabled?: boolean;
  /** Overrides `field.required`. */
  required?: boolean;
  /** Labels of the current ref values (e.g. `item.refs`). */
  refs?: Refs | undefined;
  /** Extra lookup filters for ref pickers, e.g. `{'f.project_id': 'in:prj_…'}`. */
  lookupFilters?: SearchRecord | undefined;
  /** IDs a ref picker must not offer. */
  excludeIds?: readonly string[] | undefined;
  /** Codes that stay selectable although inactive (e.g. the stored value). */
  keepCodes?: readonly string[] | undefined;
  /** Extra description below the label. */
  description?: ReactNode;
  size?: 'xs' | 'sm';
}

export function FieldLabel({ field }: { field: FieldSpec }) {
  return (
    <span>
      {field.label}
      <HelpTooltip label={field.label} help={field.help} />
    </span>
  );
}

const emptyToNull = (text: string): string | null => (text === '' ? null : text);

/** Types that are read-only in Phase 1 (docs/UI.md §4.1). */
export const isReadOnlyType = (field: FieldSpec): boolean =>
  field.system || field.derived || field.virtual || field.type === 'doc_links' || field.type === 'json';

export function FieldInput({
  field,
  value,
  onChange,
  error,
  disabled = false,
  required,
  refs,
  lookupFilters,
  excludeIds,
  keepCodes = [],
  description,
  size = 'sm',
}: FieldInputProps) {
  const label = <FieldLabel field={field} />;
  const common = {
    label,
    description,
    error: error ?? fieldValueError(field, value),
    disabled,
    required: required ?? field.required,
    size,
  };

  if (isReadOnlyType(field)) {
    return (
      <Input.Wrapper label={label} description={description ?? 'Read-only'} size={size}>
        <div>
          <ValueDisplay field={field} value={value} refs={refs} variant="full" />
        </div>
      </Input.Wrapper>
    );
  }

  switch (field.type) {
    case 'text':
      return (
        <Textarea
          {...common}
          autosize
          minRows={2}
          maxRows={12}
          value={asString(value) ?? ''}
          onChange={(event) => {
            onChange(emptyToNull(event.currentTarget.value));
          }}
        />
      );
    case 'slug':
      return (
        <TextInput
          {...common}
          description={description ?? SLUG_HINT}
          value={asString(value) ?? ''}
          onChange={(event) => {
            onChange(emptyToNull(event.currentTarget.value));
          }}
        />
      );
    case 'url':
      return (
        <TextInput
          {...common}
          inputMode="url"
          placeholder="https://"
          value={asString(value) ?? ''}
          onChange={(event) => {
            onChange(emptyToNull(event.currentTarget.value));
          }}
        />
      );
    case 'partial_date':
      return (
        <TextInput
          {...common}
          description={description ?? PARTIAL_DATE_HINT}
          value={asString(value) ?? ''}
          onChange={(event) => {
            onChange(emptyToNull(event.currentTarget.value.trim()));
          }}
        />
      );
    case 'vocab':
      return (
        <VocabSelect
          {...common}
          vocabulary={field.vocabulary}
          value={asString(value)}
          keep={keepCodes}
          onChange={onChange}
        />
      );
    case 'vocab_list':
      return (
        <VocabMultiSelect
          {...common}
          vocabulary={field.vocabulary}
          value={asStringArray(value)}
          keep={keepCodes}
          onChange={onChange}
        />
      );
    case 'bool':
      return (
        <Switch
          label={label}
          description={description}
          error={common.error}
          disabled={disabled}
          size={size}
          checked={value === true}
          onChange={(event) => {
            onChange(event.currentTarget.checked);
          }}
        />
      );
    case 'int':
    case 'number':
      return (
        <NumberInput
          {...common}
          allowDecimal={field.type === 'number'}
          value={asNumber(value) ?? ''}
          onChange={(next) => {
            onChange(typeof next === 'number' ? next : null);
          }}
        />
      );
    case 'url_list':
    case 'string_list':
      return (
        <LineListInput
          {...common}
          description={description ?? 'One per line'}
          value={asStringArray(value)}
          onChange={onChange}
        />
      );
    case 'alias_list':
      return (
        <AliasListInput
          label={label}
          description={description}
          error={error}
          disabled={disabled}
          value={asAliases(value)}
          onChange={(aliases) => {
            onChange(aliases.map((alias) => ({ ...alias })));
          }}
        />
      );
    case 'ref':
      return (
        <RefSelect
          {...common}
          types={field.ref_types ?? []}
          value={asString(value)}
          currentRef={refs?.[field.name]}
          lookupFilters={lookupFilters}
          excludeIds={excludeIds}
          onChange={onChange}
        />
      );
    case 'datetime':
      return <DateTimeUtcInput {...common} value={asString(value)} onChange={onChange} />;
    case 'date':
      return (
        <DateInput
          {...common}
          valueFormat="YYYY-MM-DD"
          clearable={!common.required}
          value={asString(value)}
          onChange={onChange}
          popoverProps={{ withinPortal: true }}
        />
      );
    default:
      return (
        <TextInput
          {...common}
          value={asString(value) ?? ''}
          onChange={(event) => {
            onChange(emptyToNull(event.currentTarget.value));
          }}
        />
      );
  }
}
