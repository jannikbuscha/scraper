// Vocabulary inputs: searchable by label and code; inactive codes are hidden
// unless they are the current value (docs/UI.md §4.1).
import {
  Group,
  MultiSelect,
  Pill,
  Select,
  Text,
  type ComboboxItem,
  type ComboboxRenderPillInput,
  type OptionsFilter,
} from '@mantine/core';
import type { ReactNode } from 'react';

import { useVocabIndex } from '../../../hooks/useVocabIndex';
import { selectableTerms, termLabel } from '../../../lib/vocab';

interface CommonProps {
  vocabulary: string | null;
  label: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  required?: boolean;
  size?: 'xs' | 'sm';
  /** Codes that stay selectable although inactive (e.g. the stored value). */
  keep?: readonly string[];
}

/** Matches the search against label and code. */
const filterByLabelOrCode: OptionsFilter = ({ options, search }) => {
  const needle = search.trim().toLocaleLowerCase();
  if (!needle) return options;
  return options.filter(
    (option) =>
      'value' in option &&
      (option.label.toLocaleLowerCase().includes(needle) || option.value.toLocaleLowerCase().includes(needle)),
  );
};

function renderOption({ option }: { option: ComboboxItem }) {
  return (
    <Group gap={8} wrap="nowrap" justify="space-between" w="100%">
      <Text size="sm">
        <bdi>{option.label}</bdi>
      </Text>
      <Text size="xs" c="dimmed" ff="monospace">
        {option.value}
      </Text>
    </Group>
  );
}

function useTermOptions(vocabulary: string | null, keep: readonly string[]): ComboboxItem[] {
  const index = useVocabIndex();
  const options = selectableTerms(index, vocabulary, keep).map((term) => {
    const label = termLabel(index, vocabulary, term.code);
    return { value: term.code, label: term.active ? label : `${label} (inactive)` };
  });
  // Keep stored codes that the vocabulary does not know (yet), so nothing is lost silently.
  for (const code of new Set(keep)) if (!options.some((o) => o.value === code)) options.push({ value: code, label: code });
  return options;
}

interface VocabSelectProps extends CommonProps {
  value: string | null;
  onChange: (value: string | null) => void;
}

export function VocabSelect({ vocabulary, value, onChange, keep = [], required = false, size = 'sm', ...rest }: VocabSelectProps) {
  const data = useTermOptions(vocabulary, value ? [...keep, value] : keep);
  return (
    <Select
      {...rest}
      size={size}
      data={data}
      value={value}
      onChange={onChange}
      searchable
      clearable={!required}
      required={required}
      filter={filterByLabelOrCode}
      renderOption={renderOption}
      nothingFoundMessage="No matching term"
      comboboxProps={{ withinPortal: true }}
    />
  );
}

interface VocabMultiSelectProps extends CommonProps {
  value: string[];
  onChange: (value: string[]) => void;
  /** Marks the first value as the main one (a field value; not for bulk add/remove). */
  markMain?: boolean;
}

/** Keeps the selection order; the first value is the main one and pills can be reordered. */
export function VocabMultiSelect({
  vocabulary,
  value,
  onChange,
  keep = [],
  required = false,
  size = 'sm',
  markMain = true,
  ...rest
}: VocabMultiSelectProps) {
  const data = useTermOptions(vocabulary, [...keep, ...value]);
  const renderPill = ({ option, onRemove, disabled, reorderProps }: ComboboxRenderPillInput) => {
    const isMain = markMain && option.value === value[0] && value.length > 1;
    return (
      <Pill withRemoveButton={!disabled} onRemove={onRemove} disabled={disabled} {...reorderProps} fw={isMain ? 700 : undefined}>
        <bdi>{option.label}</bdi>
        {isMain && ' · main'}
      </Pill>
    );
  };
  return (
    <MultiSelect
      {...rest}
      size={size}
      data={data}
      value={value}
      onChange={onChange}
      searchable
      clearable={!required}
      required={required}
      filter={filterByLabelOrCode}
      renderOption={renderOption}
      renderPill={renderPill}
      withPillsReorder
      nothingFoundMessage="No matching term"
      comboboxProps={{ withinPortal: true }}
    />
  );
}
