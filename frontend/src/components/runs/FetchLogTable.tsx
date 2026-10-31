// The fetch log of a run (docs/UI.md §8.3): one row per request attempt and
// per URL the client decided not to request (outcome `refused`).
import { Badge, Table, Text } from '@mantine/core';

import type { FetchLogEntry } from '../../api/acquisition-types';
import { ExternalLink } from '../ExternalLink';
import { SnapshotLink } from '../SnapshotLink';
import { Timestamp } from '../Timestamp';
import { FETCH_OUTCOME_COLORS, formatBytes, formatCount } from './run-labels';
import classes from './runs.module.css';

export function FetchLogTable({ entries }: { entries: readonly FetchLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No requests.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={1000}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={130}>Time</Table.Th>
            <Table.Th w={70}>Method</Table.Th>
            <Table.Th>URL</Table.Th>
            <Table.Th w={70}>Status</Table.Th>
            <Table.Th w={140}>Outcome</Table.Th>
            <Table.Th w={90} ta="right">
              Bytes
            </Table.Th>
            <Table.Th w={90} ta="right">
              Duration
            </Table.Th>
            <Table.Th w={70} ta="right">
              Attempt
            </Table.Th>
            <Table.Th w={90}>Snapshot</Table.Th>
            <Table.Th>Error</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {entries.map((entry) => (
            <Table.Tr key={entry.id}>
              <Table.Td className={classes.cell}>
                <Timestamp value={entry.at} />
              </Table.Td>
              <Table.Td className={classes.cell}>{entry.method}</Table.Td>
              <Table.Td className={classes.cell}>
                <ExternalLink url={entry.url} />
                {entry.purpose === 'robots' && (
                  <Text span size="xs" c="dimmed">
                    {' '}
                    robots.txt
                  </Text>
                )}
              </Table.Td>
              <Table.Td className={classes.cell}>{entry.status ?? '—'}</Table.Td>
              <Table.Td className={classes.cell}>
                <Badge size="xs" variant="light" color={FETCH_OUTCOME_COLORS[entry.outcome]}>
                  {entry.outcome}
                </Badge>
              </Table.Td>
              <Table.Td className={classes.cell} ta="right">
                {formatBytes(entry.bytes)}
              </Table.Td>
              <Table.Td className={classes.cell} ta="right">
                {entry.duration_ms === null ? '—' : `${formatCount(entry.duration_ms)} ms`}
              </Table.Td>
              <Table.Td className={classes.cell} ta="right">
                {entry.attempt}
              </Table.Td>
              <Table.Td className={classes.cell}>
                {entry.raw_snapshot_id && <SnapshotLink id={entry.raw_snapshot_id} />}
              </Table.Td>
              <Table.Td className={`${classes.cell} ${classes.message}`}>
                {entry.error}
                {entry.retry_after_s !== null && (
                  <Text span size="xs" c="dimmed">
                    {' '}
                    (Retry-After {entry.retry_after_s} s)
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
