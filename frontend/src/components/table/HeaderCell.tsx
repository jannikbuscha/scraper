// Header cell (docs/UI.md §3): label with help tooltip; for sortable fields a
// sort button (click cycles asc → desc → none, shift-click adds a secondary
// sort, max 3); a filter button with an active-state dot.
import { Group, Text, UnstyledButton } from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconArrowsSort } from '@tabler/icons-react';

import type { FieldSpec } from '../../api/types';
import { clickSort, effectiveSort, MAX_SORT_FIELDS } from '../../lib/query-string';
import { HelpTooltip } from '../HelpTooltip';
import { FilterPopover } from './filters/FilterPopover';
import classes from './table.module.css';
import { useTableContext } from './TableContext';

export function HeaderCell({ field }: { field: FieldSpec }) {
  const { typeMeta, search, setSearch } = useTableContext();
  const sorts = effectiveSort(search, typeMeta.default_sort);
  const index = sorts.findIndex((term) => term.field === field.name);
  const term = index >= 0 ? sorts[index] : undefined;
  const isDefault = search.sort === undefined;

  const label = field.sortable ? (
    <UnstyledButton
      className={classes.sortButton}
      title={`Sort by ${field.label}. Shift-click adds a secondary sort (max ${MAX_SORT_FIELDS}).`}
      onClick={(event) => {
        const additive = event.shiftKey;
        setSearch((previous) => clickSort(previous, typeMeta.default_sort, field.name, additive));
      }}
    >
      <span>{field.label}</span>
      {term ? (
        <span className={isDefault ? classes.defaultSort : classes.activeSort}>
          {term.desc ? <IconArrowDown size={13} aria-hidden /> : <IconArrowUp size={13} aria-hidden />}
          {sorts.length > 1 && <sup>{index + 1}</sup>}
        </span>
      ) : (
        <IconArrowsSort size={13} className={classes.sortHint} aria-hidden />
      )}
    </UnstyledButton>
  ) : (
    <Text span size="sm" fw={600}>
      {field.label}
    </Text>
  );

  return (
    <Group gap={2} wrap="nowrap" justify="space-between">
      <Group gap={0} wrap="nowrap">
        {label}
        <HelpTooltip label={field.label} help={field.help} />
      </Group>
      <FilterPopover field={field} />
    </Group>
  );
}
