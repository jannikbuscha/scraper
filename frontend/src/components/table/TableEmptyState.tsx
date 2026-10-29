// Empty table (docs/UI.md §3): explains the active filters, with vocabulary
// labels and lookup labels for referenced IDs; each can be removed on its own
// (the table header with its filter popovers stays visible above), or all at
// once with "Clear filters". A page past the end of the results offers the
// first page instead.
import { ActionIcon, Button, EmptyState, Group, List, Text } from '@mantine/core';
import { IconFilterOff, IconTable, IconX } from '@tabler/icons-react';

import { useLookupIds } from '../../api/lookup';
import type { FieldSpec } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import { describeFilter, type ValueLabeler } from '../../lib/filter-describe';
import {
  activeFilters,
  clearFilters,
  getDeletedMode,
  parseRefFilter,
  setFilter,
  withDeletedMode,
  withPage,
  withQuery,
  type SearchRecord,
} from '../../lib/query-string';
import { termLabel } from '../../lib/vocab';
import { useTableContext } from './TableContext';

/** One active restriction of the empty result, with the update that removes it. */
interface ActiveLine {
  key: string;
  text: string;
  remove: (search: SearchRecord) => SearchRecord;
}

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
  const lines: ActiveLine[] = [
    ...(search.q ? [{ key: 'q', text: `Search: “${search.q}”`, remove: (previous: SearchRecord) => withQuery(previous, '') }] : []),
    ...filters.map(([name, raw]): ActiveLine => {
      const field = byName.get(name);
      return {
        key: `f.${name}`,
        text: field ? describeFilter(field, raw, label) : `${name}: ${raw}`,
        remove: (previous) => setFilter(previous, name, null),
      };
    }),
    ...(deleted === 'exclude'
      ? []
      : [
          {
            key: 'deleted',
            text: deleted === 'only' ? 'Only deleted rows' : 'Deleted rows included',
            remove: (previous: SearchRecord) => withDeletedMode(previous, 'exclude'),
          },
        ]),
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
      <List size="sm" ta="left" aria-label="Active filters" listStyleType="none">
        {lines.map((line) => (
          <List.Item key={line.key}>
            <Group gap={4} wrap="nowrap">
              <Text span size="sm">
                <bdi>{line.text}</bdi>
              </Text>
              <ActionIcon
                size="sm"
                variant="subtle"
                color="gray"
                aria-label={`Remove: ${line.text}`}
                onClick={() => {
                  setSearch((previous) => line.remove(previous));
                }}
              >
                <IconX size={14} aria-hidden />
              </ActionIcon>
            </Group>
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
