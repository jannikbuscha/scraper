// multiselect filter: checkboxes with counts from /facets (loaded when the
// popover opens) plus "(empty)" → the ~empty token; operators in / not in for
// single values, any / all / none for list fields (docs/UI.md §3).
import { Checkbox, Group, Loader, ScrollArea, SegmentedControl, Stack, Text, TextInput } from '@mantine/core';
import { useState, type ReactNode } from 'react';

import { useFacets } from '../../../api/queries';
import type { FacetValue } from '../../../api/types';
import { useVocabIndex } from '../../../hooks/useVocabIndex';
import { pick, pluralize } from '../../../lib/format';
import {
  EMPTY_TOKEN,
  facetQueryString,
  formatMultiselectFilter,
  multiselectOps,
  parseMultiselectFilter,
  type MultiselectOp,
} from '../../../lib/query-string';
import { termLabel } from '../../../lib/vocab';
import { errorMessage } from '../../feedback';
import { useTableContext } from '../TableContext';
import { FilterFormFrame, type FilterFormProps } from './FilterFormFrame';

const OP_LABELS: Record<MultiselectOp, string> = {
  in: 'is any of',
  nin: 'is none of',
  any: 'has any of',
  all: 'has all of',
  none: 'has none of',
};

/** Long lists get a search box. */
const SEARCHABLE_FROM = 12;

/** Value label with its count. */
function FacetLabel({ children, count, title }: { children: ReactNode; count: number; title?: string }) {
  return (
    <Group gap={8} justify="space-between" wrap="nowrap" w={230}>
      <Text size="sm" span title={title} truncate>
        {children}
      </Text>
      <Text size="xs" c="dimmed" span>
        {count}
      </Text>
    </Group>
  );
}

/** The checkbox's accessible name, the same in every browser: "Label (3 rows)". */
const facetName = (label: string, count: number): string => `${label} (${pluralize(count, 'row')})`;

export function MultiselectFilterForm({ field, raw, onApply }: FilterFormProps) {
  const { type, search } = useTableContext();
  const vocab = useVocabIndex();
  const isList = field.type === 'vocab_list';
  const ops = multiselectOps(isList);
  const initial = parseMultiselectFilter(raw, isList);
  const [op, setOp] = useState<MultiselectOp>(initial?.op ?? ops[0] ?? 'in');
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set(initial?.values ?? []));
  const [needle, setNeedle] = useState('');
  const facets = useFacets(type, field.name, facetQueryString(search, field.name), true);

  // Selected codes without a facet row (e.g. inactive terms) stay visible.
  const values: FacetValue[] = [...(facets.data?.values ?? [])];
  for (const code of selected) {
    if (code !== EMPTY_TOKEN && !values.some((v) => v.value === code)) {
      values.push({ value: code, label: termLabel(vocab, field.vocabulary, code), count: 0 });
    }
  }
  const query = needle.trim().toLocaleLowerCase();
  const visible = query
    ? values.filter((v) => v.label.toLocaleLowerCase().includes(query) || v.value.toLocaleLowerCase().includes(query))
    : values;

  const toggle = (value: string, checked: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (checked) next.add(value);
      else next.delete(value);
      return next;
    });
  };
  // Values in facet (vocabulary) order, the empty token last: a canonical URL.
  const ordered = [...values.map((v) => v.value), EMPTY_TOKEN].filter((value) => selected.has(value));

  return (
    <FilterFormFrame
      title={field.label}
      onApply={() => {
        onApply(formatMultiselectFilter({ op, values: ordered }));
      }}
      onClear={() => {
        onApply(null);
      }}
    >
      <SegmentedControl
        size="xs"
        fullWidth
        aria-label="Condition"
        data={ops.map((value) => ({ value, label: OP_LABELS[value] }))}
        value={op}
        onChange={(value) => {
          setOp(pick(ops, value) ?? op);
        }}
      />
      {values.length >= SEARCHABLE_FROM && (
        <TextInput
          size="xs"
          placeholder="Search values"
          aria-label="Search values"
          value={needle}
          onChange={(event) => {
            setNeedle(event.currentTarget.value);
          }}
        />
      )}
      {facets.isPending ? (
        <Group gap={6}>
          <Loader size="xs" />
          <Text size="xs" c="dimmed">
            Loading values…
          </Text>
        </Group>
      ) : facets.isError ? (
        <Text size="xs" c="red">
          {errorMessage(facets.error)}
        </Text>
      ) : (
        <ScrollArea.Autosize mah={260} type="auto" offsetScrollbars>
          <Stack gap={4}>
            {visible.map((facet) => (
              <Checkbox
                key={facet.value}
                size="xs"
                aria-label={facetName(facet.label, facet.count)}
                checked={selected.has(facet.value)}
                onChange={(event) => {
                  toggle(facet.value, event.currentTarget.checked);
                }}
                label={
                  <FacetLabel count={facet.count} title={facet.value}>
                    <bdi>{facet.label}</bdi>
                  </FacetLabel>
                }
              />
            ))}
            <Checkbox
              size="xs"
              aria-label={facetName('(empty)', facets.data.empty_count)}
              checked={selected.has(EMPTY_TOKEN)}
              disabled={op === 'all'}
              onChange={(event) => {
                toggle(EMPTY_TOKEN, event.currentTarget.checked);
              }}
              label={
                <FacetLabel count={facets.data.empty_count}>
                  <em>(empty)</em>
                </FacetLabel>
              }
            />
          </Stack>
        </ScrollArea.Autosize>
      )}
    </FilterFormFrame>
  );
}
