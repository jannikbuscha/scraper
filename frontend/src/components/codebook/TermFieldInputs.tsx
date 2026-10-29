// Inputs of the term forms, generated from the registry fields of
// vocabulary terms (FieldInput per type). Two fields follow codebook rules
// (docs/DATA_MODEL.md §7): `active` cannot be switched off for fixed codes,
// and `replaced_by` picks an active code of the same vocabulary and is only
// allowed for inactive terms. Event types add the counts_as_modification
// switch, whose change recomputes derived values.
import { Alert, Select, Switch } from '@mantine/core';
import type { ReactNode } from 'react';

import type { FieldSpec, JsonObject, JsonValue, Vocabulary } from '../../api/types';
import { asString } from '../../lib/format';
import { FieldInput, FieldLabel } from '../fields/FieldInput';
import { replacementCodes } from './term-form';

interface TermFieldInputsProps {
  fields: readonly FieldSpec[];
  values: JsonObject;
  onChange: (name: string, value: JsonValue) => void;
  errors: Readonly<Record<string, ReactNode>>;
  vocabulary: Vocabulary;
  /** The term's own code (not offered as its replacement); null for a new term. */
  ownCode: string | null;
  /** A fixed code cannot be deactivated. */
  fixed: boolean;
}

interface ReplacedBySelectProps {
  field: FieldSpec;
  value: string | null;
  /** Replacements are allowed only for inactive terms. */
  inactive: boolean;
  onChange: (value: string | null) => void;
  error: ReactNode;
  vocabulary: Vocabulary;
  ownCode: string | null;
}

function ReplacedBySelect({ field, value, inactive, onChange, error, vocabulary, ownCode }: ReplacedBySelectProps) {
  const options = replacementCodes(vocabulary, ownCode).map((term) => ({
    value: term.code,
    label: `${term.label_en} (${term.code})`,
  }));
  // A stored code that is no longer offered stays visible.
  if (value !== null && !options.some((option) => option.value === value)) options.push({ value, label: value });
  return (
    <Select
      label={<FieldLabel field={field} />}
      description={inactive ? 'The active code that replaces this one.' : 'Only for inactive terms.'}
      data={options}
      value={value}
      onChange={onChange}
      disabled={!inactive}
      searchable
      clearable
      error={error}
      comboboxProps={{ withinPortal: true }}
    />
  );
}

export function TermFieldInputs({ fields, values, onChange, errors, vocabulary, ownCode, fixed }: TermFieldInputsProps) {
  return (
    <>
      {fields.map((field) => {
        if (field.name === 'replaced_by') {
          return (
            <ReplacedBySelect
              key={field.name}
              field={field}
              value={asString(values[field.name] ?? null)}
              inactive={values.active === false}
              onChange={(value) => {
                onChange(field.name, value);
              }}
              error={errors[field.name]}
              vocabulary={vocabulary}
              ownCode={ownCode}
            />
          );
        }
        const lockedActive = field.name === 'active' && fixed;
        return (
          <FieldInput
            key={field.name}
            field={field}
            value={values[field.name] ?? null}
            error={errors[field.name]}
            disabled={lockedActive}
            description={lockedActive ? 'Fixed code: program logic uses it, so it cannot be deactivated.' : undefined}
            onChange={(value) => {
              onChange(field.name, value);
            }}
          />
        );
      })}
    </>
  );
}

interface ModificationSwitchProps {
  checked: boolean;
  /** The value differs from the stored one: saving recomputes derived values. */
  changed: boolean;
  onChange: (checked: boolean) => void;
}

/** `attributes.counts_as_modification` of event types (decision D-2). */
export function ModificationSwitch({ checked, changed, onChange }: ModificationSwitchProps) {
  return (
    <>
      <Switch
        label="Counts as modification"
        description="Events of this type count as a modification for the derived war trajectory (“adapted in war”)."
        checked={checked}
        onChange={(event) => {
          onChange(event.currentTarget.checked);
        }}
      />
      {changed && (
        <Alert color="yellow" variant="light" title="Derived values will be recomputed">
          Saving recomputes the derived values (launch, period, war trajectory) of every project and service.
        </Alert>
      )}
    </>
  );
}
