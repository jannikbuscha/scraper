// The runs list (docs/UI.md §8.3): collector, status, trigger, mode, start,
// duration, requests, snapshots, created, updated, proposals opened, errors
// and warnings, and a "replay" badge for runs that answered from fixtures.
// A row click opens the run (ctrl- or middle-click: a new tab).
import { Badge, Group, Table, Text } from '@mantine/core';
import { useNavigate } from '@tanstack/react-router';
import type { MouseEvent } from 'react';

import type { Run } from '../../api/acquisition-types';
import { AnchorLink } from '../AnchorLink';
import { Timestamp } from '../Timestamp';
import { formatCount, formatDuration, isReplay } from './run-labels';
import { RunStatusBadge } from './RunStatusBadge';
import classes from './runs.module.css';

/** Clicks on links and buttons inside a row keep their own behaviour. */
const isInteractive = (target: EventTarget | null): boolean =>
  target instanceof Element && target.closest('a, button, input, label') !== null;

export function RunsTable({ runs, showCollector = true }: { runs: readonly Run[]; showCollector?: boolean }) {
  const navigate = useNavigate();
  const open = (event: MouseEvent, run: Run) => {
    if (isInteractive(event.target)) return;
    if (event.ctrlKey || event.metaKey || event.button === 1) {
      window.open(`/runs/${encodeURIComponent(run.id)}`, '_blank', 'noopener');
      return;
    }
    void navigate({ to: '/runs/$id', params: { id: run.id } });
  };
  return (
    <Table.ScrollContainer minWidth={980}>
      <Table highlightOnHover className={classes.runs}>
        <Table.Thead>
          <Table.Tr>
            {showCollector && <Table.Th>Collector</Table.Th>}
            <Table.Th>Status</Table.Th>
            <Table.Th>Trigger</Table.Th>
            <Table.Th>Mode</Table.Th>
            <Table.Th>Started</Table.Th>
            <Table.Th ta="right">Duration</Table.Th>
            <Table.Th ta="right">Requests</Table.Th>
            <Table.Th ta="right">Snapshots</Table.Th>
            <Table.Th ta="right">Created</Table.Th>
            <Table.Th ta="right">Updated</Table.Th>
            <Table.Th ta="right">Proposals</Table.Th>
            <Table.Th ta="right">Errors / warnings</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {runs.map((run) => (
            <Table.Tr
              key={run.id}
              className={classes.clickable}
              onClick={(event) => {
                open(event, run);
              }}
              onAuxClick={(event) => {
                if (event.button === 1) open(event, run);
              }}
            >
              {showCollector && (
                <Table.Td>
                  <AnchorLink to="/runs/$id" params={{ id: run.id }} aria-label={`Open run ${run.id}`}>
                    <bdi>{run.collector_label ?? run.collector}</bdi>
                  </AnchorLink>
                </Table.Td>
              )}
              <Table.Td>
                <Group gap={4} wrap="nowrap">
                  <RunStatusBadge status={run.status} />
                  {isReplay(run) && (
                    <Badge size="xs" variant="outline" color="gray" title="Answered from stored fixtures">
                      replay
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>{run.trigger}</Table.Td>
              <Table.Td>{run.mode}</Table.Td>
              <Table.Td>
                {showCollector ? (
                  <Timestamp value={run.started_at} />
                ) : (
                  <AnchorLink to="/runs/$id" params={{ id: run.id }} aria-label={`Open run ${run.id}`}>
                    <Timestamp value={run.started_at} />
                  </AnchorLink>
                )}
              </Table.Td>
              <Table.Td ta="right">{formatDuration(run.duration_s)}</Table.Td>
              <Table.Td ta="right">{formatCount(run.stats.requests)}</Table.Td>
              <Table.Td ta="right">{formatCount(run.stats.snapshots)}</Table.Td>
              <Table.Td ta="right">{formatCount(run.stats.entities_created)}</Table.Td>
              <Table.Td ta="right">{formatCount(run.stats.entities_updated)}</Table.Td>
              <Table.Td ta="right">{formatCount(run.stats.proposals_opened)}</Table.Td>
              <Table.Td ta="right">
                <Text span size="sm" c={run.stats.errors > 0 ? 'red' : undefined}>
                  {formatCount(run.stats.errors)}
                </Text>
                {' / '}
                <Text span size="sm" c={run.stats.warnings > 0 ? 'orange' : undefined}>
                  {formatCount(run.stats.warnings)}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
