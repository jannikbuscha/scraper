// Revision list of one record (docs/UI.md §4.2): version, time, author,
// channel and action, note, changed fields. Optionally selectable (show one
// revision's diff) and with a compare mode that picks two versions.
import { Badge, Checkbox, Table, Text, UnstyledButton } from '@mantine/core';
import type { ReactNode } from 'react';

import type { RevisionSummary } from '../../api/types';
import { Timestamp } from '../Timestamp';
import classes from './history.module.css';
import { ActionBadge, ChangedFieldChips, ChannelBadge } from './RevisionBadges';

export interface CompareSelection {
  /** Picked versions (at most two). */
  selected: readonly number[];
  onToggle: (version: number) => void;
}

interface RevisionListProps {
  revisions: readonly RevisionSummary[];
  /** Registry labels for the changed-field chips. */
  fieldLabels?: Readonly<Record<string, string>>;
  /** The record's current version, marked "current". */
  currentVersion?: number | undefined;
  selectedVersion?: number | null | undefined;
  onSelect?: ((revision: RevisionSummary) => void) | undefined;
  compare?: CompareSelection | undefined;
  /** Per-row actions, e.g. "Restore this version". */
  renderActions?: ((revision: RevisionSummary) => ReactNode) | undefined;
}

export function RevisionList({
  revisions,
  fieldLabels,
  currentVersion,
  selectedVersion,
  onSelect,
  compare,
  renderActions,
}: RevisionListProps) {
  if (revisions.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No revisions.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table highlightOnHover={onSelect !== undefined}>
        <Table.Thead>
          <Table.Tr>
            {compare && <Table.Th w={70}>Compare</Table.Th>}
            <Table.Th w={80}>Version</Table.Th>
            <Table.Th w={130}>Time</Table.Th>
            <Table.Th>Author</Table.Th>
            <Table.Th>Change</Table.Th>
            <Table.Th>Note</Table.Th>
            <Table.Th>Changed fields</Table.Th>
            {renderActions && <Table.Th>Actions</Table.Th>}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {revisions.map((revision) => {
            const selected = selectedVersion === revision.version;
            const picked = compare?.selected.includes(revision.version) ?? false;
            return (
              <Table.Tr
                key={revision.id}
                className={selected ? classes.selectedRow : undefined}
                aria-selected={onSelect ? selected : undefined}
              >
                {compare && (
                  <Table.Td>
                    <Checkbox
                      aria-label={`Compare version ${revision.version}`}
                      checked={picked}
                      disabled={!picked && compare.selected.length >= 2}
                      onChange={() => {
                        compare.onToggle(revision.version);
                      }}
                    />
                  </Table.Td>
                )}
                <Table.Td>
                  {onSelect ? (
                    <UnstyledButton
                      onClick={() => {
                        onSelect(revision);
                      }}
                      aria-pressed={selected}
                      aria-label={`Show the changes of version ${revision.version}`}
                      fw={600}
                    >
                      v{revision.version}
                    </UnstyledButton>
                  ) : (
                    <Text span fw={600}>
                      v{revision.version}
                    </Text>
                  )}
                  {revision.version === currentVersion && (
                    <Badge size="xs" variant="light" ml={6}>
                      current
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  <Timestamp value={revision.at} />
                </Table.Td>
                <Table.Td>
                  <bdi>{revision.author}</bdi>
                </Table.Td>
                <Table.Td>
                  <ChannelBadge channel={revision.channel} /> <ActionBadge action={revision.action} />
                  {revision.restored_from_version !== null && (
                    <Text span size="xs" c="dimmed">
                      {' '}
                      from v{revision.restored_from_version}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td className={classes.note}>{revision.note}</Table.Td>
                <Table.Td>
                  <ChangedFieldChips fields={revision.changed_fields} labels={fieldLabels} />
                </Table.Td>
                {renderActions && <Table.Td>{renderActions(revision)}</Table.Td>}
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
