// A read-only list of related records with an empty state (docs/UI.md §4.1
// "Related panels"); columns are registry fields of the listed type.
import { Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

import { useEntityList } from '../../api/queries';
import type { EntityType, Meta } from '../../api/types';
import { isTableType, TABLE_PATHS } from '../../lib/entity';
import { canonicalQuery, type SearchRecord } from '../../lib/query-string';
import { AnchorLink } from '../AnchorLink';
import { EntityLink } from '../EntityLink';
import { ErrorAlert } from '../feedback';
import { FieldValue } from '../fields/FieldValue';
import classes from './detail.module.css';

const RELATED_PAGE_SIZE = 100;

export interface RelatedListProps {
  title: string;
  type: EntityType;
  /** List parameters, e.g. `{'f.project_id': 'in:prj_…', sort: 'date'}`. */
  query: SearchRecord;
  /** Registry fields of `type` shown as columns. */
  columns: readonly string[];
  emptyText: string;
  meta: Meta;
  /** E.g. "+ Add service". */
  action?: ReactNode;
}

export function RelatedList({ title, type, query, columns, emptyText, meta, action }: RelatedListProps) {
  const list = useEntityList(type, canonicalQuery({ ...query, page_size: String(RELATED_PAGE_SIZE) }));
  const typeMeta = meta.entity_types[type];
  const specs = columns.flatMap((name) => typeMeta?.fields.find((field) => field.name === name) ?? []);
  // Types with a detail page are listed by their linked label.
  const withLabel = isTableType(type);
  const total = list.data?.total;
  const items = list.data?.items ?? [];

  let body: ReactNode;
  if (list.isPending) body = <Loader size="xs" />;
  else if (list.isError) {
    body = (
      <ErrorAlert
        title={`Could not load the ${title.toLowerCase()}`}
        error={list.error}
        onRetry={() => void list.refetch()}
      />
    );
  } else if (items.length === 0) {
    body = (
      <Text size="sm" c="dimmed">
        {emptyText}
      </Text>
    );
  } else {
    body = (
      <Table.ScrollContainer minWidth={480}>
        <Table className={classes.relatedTable} withTableBorder>
          <Table.Thead>
            <Table.Tr>
              {withLabel && <Table.Th>{typeMeta?.label ?? type}</Table.Th>}
              {specs.map((field) => (
                <Table.Th key={field.name}>{field.label}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((row) => (
              <Table.Tr key={row.id}>
                {withLabel && (
                  <Table.Td>
                    <EntityLink id={row.id} label={row.label} type={row.type} deleted={row.deleted_at !== null} />
                  </Table.Td>
                )}
                {specs.map((field) => (
                  <Table.Td key={field.name}>
                    <FieldValue field={field} item={row} variant="cell" />
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    );
  }

  return (
    <Stack gap={4} component="section" aria-label={title}>
      <Group justify="space-between" gap="xs">
        <Group gap="xs" align="baseline">
          <Title order={3}>{title}</Title>
          {total !== undefined && (
            <Text span size="sm" c="dimmed">
              {total}
            </Text>
          )}
        </Group>
        <Group gap="xs">
          {action}
          {isTableType(type) && total !== undefined && total > 0 && (
            <AnchorLink to={TABLE_PATHS[type]} search={query} size="sm">
              Open in table
            </AnchorLink>
          )}
        </Group>
      </Group>
      {body}
      {total !== undefined && total > items.length && (
        <Text size="xs" c="dimmed">
          Showing the first {items.length} of {total}.
        </Text>
      )}
    </Stack>
  );
}
