// Empty table (docs/UI.md §3): explains the active filters, with vocabulary
// labels and lookup labels for referenced IDs, and offers "Clear filters".
// A page past the end of the results offers the first page instead.
import { Button, EmptyState, List } from '@mantine/core';
import { IconFilterOff, IconTable } from '@tabler/icons-react';

import { useLookupIds } from '../../api/lookup';
import type { FieldSpec } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import { describeFilter, type ValueLabeler } from '../../lib/filter-describe';
import { activeFilters, clearFilters, getDeletedMode, parseRefFilter, withPage } from '../../lib/query-string';
import { termLabel } from '../../lib/vocab';
import { useTableContext } from './TableContext';

/** IDs named by the ref filters, to label them via lookup. */
function refFilterIds(filters: readonly [string, string][], byName: ReadonlyMap<string, FieldSpec>): string[] {
  return filters.flatMap(([name, raw]) => {
    if (byName.get(name)?.filter !== 'ref') return [];
    const value = parseRefFilter(raw);
    return value && value.op !== 'empty' ? value.ids : [];
  });
}

export function TableEmptyState({ total }: { total: number }) {
  const { typeMeta, search, setSearch } = useTableContext();
  const vocab = useVocabIndex();
  const byName = new Map(typeMeta.fields.map((field) => [field.name, field]));
  const filters = activeFilters(search);
  const lookup = useLookupIds(refFilterIds(filters, byName));
  const plural = typeMeta.label_plural.toLowerCase();

  if (total > 0) {
    return (
      <EmptyState
        icon={<IconTable size={28} />}
        title="This page is past the end of the results"
        description={`The current filters match ${total} ${total === 1 ? 'row' : 'rows'}.`}
      >
        <EmptyState.Actions>
          <Button
            variant="light"
            onClick={() => {
              setSearch((previous) => withPage(previous, 1));
            }}
          >
            Go to the first page
          </Button>
        </EmptyState.Actions>
      </EmptyState>
    );
  }

  const label: ValueLabeler = (field, value) =>
    field.filter === 'ref' ? (lookup.byId.get(value)?.label ?? value) : termLabel(vocab, field.vocabulary, value);
  const deleted = getDeletedMode(search);
  const lines = [
    ...(search.q ? [`Search: “${search.q}”`] : []),
    ...filters.map(([name, raw]) => {
      const field = byName.get(name);
      return field ? describeFilter(field, raw, label) : `${name}: ${raw}`;
    }),
    ...(deleted === 'only' ? ['Only deleted rows'] : deleted === 'include' ? ['Deleted rows included'] : []),
  ];

  if (lines.length === 0) {
    return <EmptyState icon={<IconTable size={28} />} title={`No ${plural} yet`} description="Records appear here once they are created." />;
  }
  return (
    <EmptyState
      icon={<IconFilterOff size={28} />}
      title={`No ${plural} match the current filters`}
      description="Active filters:"
    >
      <List size="sm" ta="left" aria-label="Active filters">
        {lines.map((line) => (
          <List.Item key={line}>
            <bdi>{line}</bdi>
          </List.Item>
        ))}
      </List>
      <EmptyState.Actions>
        <Button
          variant="light"
          onClick={() => {
            setSearch((previous) => clearFilters(previous));
          }}
        >
          Clear filters
        </Button>
      </EmptyState.Actions>
    </EmptyState>
  );
}
