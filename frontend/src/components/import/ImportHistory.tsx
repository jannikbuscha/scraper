// The past imports (docs/UI.md §8.5): file, type, status, created, counts; a
// row expands to its stored errors and conflicts and links to its changes.
// URL: page, page_size (of the history).
import { ActionIcon, Alert, Badge, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react';
import { Fragment, useState } from 'react';

import type { ImportRun } from '../../api/acquisition-types';
import { useImport, useImports } from '../../api/imports';
import type { Meta } from '../../api/types';
import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';
import { AnchorLink } from '../AnchorLink';
import { FeedPagination } from '../changes/FeedPagination';
import { ErrorAlert } from '../feedback';
import { Timestamp } from '../Timestamp';
import { PlanRows } from './PlanView';

const COLUMNS = 6;

function ImportDetails({ run, meta }: { run: ImportRun; meta: Meta }) {
  const detail = useImport(run.id, true);
  if (detail.isPending) return <Loader size="xs" />;
  if (detail.isError) return <ErrorAlert title="Could not load the import" error={detail.error} />;
  const stored = detail.data.import;
  return (
    <Stack gap="xs">
      {stored.error && (
        <Alert color="red" variant="light" title="The import failed">
          {stored.error}
        </Alert>
      )}
      <Text size="sm">
        {stored.note && (
          <>
            Note: <bdi>{stored.note}</bdi> ·{' '}
          </>
        )}
        Provenance <code>import:{stored.file_label}</code> ·{' '}
        <AnchorLink to="/changes" search={{ batch_id: stored.id }}>
          Show changes
        </AnchorLink>
      </Text>
      {stored.errors.length === 0 ? (
        <Text size="sm" c="dimmed">
          No row errors or conflicts.
        </Text>
      ) : (
        <PlanRows rows={stored.errors} type={stored.entity_type} typeMeta={meta.entity_types[stored.entity_type]} />
      )}
    </Stack>
  );
}

interface ImportHistoryProps {
  meta: Meta;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

export function ImportHistory({ meta, search, setSearch }: ImportHistoryProps) {
  const paging = Object.fromEntries(Object.entries(search).filter(([key]) => key === 'page' || key === 'page_size'));
  const imports = useImports(paging);
  const [expanded, setExpanded] = useState<string | null>(null);

  let body;
  if (imports.isError) body = <ErrorAlert title="Could not load the imports" error={imports.error} onRetry={() => void imports.refetch()} />;
  else if (imports.isPending) body = <Loader size="sm" />;
  else if (imports.data.items.length === 0) {
    body = (
      <Text size="sm" c="dimmed">
        No imports yet.
      </Text>
    );
  } else {
    body = (
      <Table.ScrollContainer minWidth={820}>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={36} />
              <Table.Th>File</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th>Rows · create · update · unchanged · conflicts · errors</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {imports.data.items.map((run) => {
              const open = expanded === run.id;
              const stats = run.stats;
              return (
                <Fragment key={run.id}>
                  <Table.Tr>
                    <Table.Td>
                      <ActionIcon
                        size="sm"
                        aria-expanded={open}
                        aria-label={`${open ? 'Hide' : 'Show'} the details of the import of ${run.filename}`}
                        onClick={() => {
                          setExpanded(open ? null : run.id);
                        }}
                      >
                        {open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                      </ActionIcon>
                    </Table.Td>
                    <Table.Td>
                      <bdi>{run.filename}</bdi>
                      {run.sheet && (
                        <Text span size="xs" c="dimmed">
                          {' '}
                          · sheet <bdi>{run.sheet}</bdi>
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>{meta.entity_types[run.entity_type]?.label ?? run.entity_type}</Table.Td>
                    <Table.Td>
                      <Badge size="sm" variant="light" color={run.status === 'done' ? 'green' : 'red'}>
                        {run.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Timestamp value={run.created_at} />
                    </Table.Td>
                    <Table.Td>
                      {[stats.rows, stats.create, stats.update, stats.unchanged, stats.conflicts, stats.errors]
                        .map((value) => value ?? 0)
                        .join(' · ')}
                    </Table.Td>
                  </Table.Tr>
                  {open && (
                    <Table.Tr>
                      <Table.Td colSpan={COLUMNS}>
                        <ImportDetails run={run} meta={meta} />
                      </Table.Td>
                    </Table.Tr>
                  )}
                </Fragment>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    );
  }

  return (
    <Stack gap="xs" component="section" aria-labelledby="import-history">
      <Title order={2} id="import-history">
        History
      </Title>
      <div aria-busy={imports.isPlaceholderData}>{body}</div>
      {imports.data && imports.data.total > 0 && <FeedPagination total={imports.data.total} search={search} setSearch={setSearch} />}
    </Stack>
  );
}
