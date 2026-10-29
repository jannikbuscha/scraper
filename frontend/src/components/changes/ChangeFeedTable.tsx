// Rows of Recent changes grouped by local day (docs/UI.md §5): time, author,
// channel and action, the record (type and label, linked to its page),
// version, changed fields and note. Expanding a row loads and shows its diff.
import { ActionIcon, Table, Text, Tooltip, VisuallyHidden } from '@mantine/core';
import { IconChevronDown, IconChevronRight, IconStack2 } from '@tabler/icons-react';
import dayjs from 'dayjs';
import { useState } from 'react';

import type { ChangeFeedItem, Meta } from '../../api/types';
import { formatUtcTimestamp, localDay, parseTimestamp } from '../../lib/format';
import { ActionBadge, ChangedFieldChips, ChannelBadge } from '../history/RevisionBadges';
import classes from './changes.module.css';
import { recordFieldLabels, recordTypeLabel } from './record-labels';
import { RevisionDiffPanel } from './RevisionDiffPanel';
import { changeTarget } from './targets';
import { TargetLink } from './TargetLink';

const COLUMNS = 8;

/** Local time of day; the day is the group heading. */
function TimeOfDay({ value }: { value: string }) {
  const date = parseTimestamp(value);
  return (
    <time dateTime={value} title={formatUtcTimestamp(value)}>
      {date ? dayjs(date).format('HH:mm') : value}
    </time>
  );
}

/** `[day, changes]` in feed order (newest first). */
function groupByDay(items: readonly ChangeFeedItem[]): [string, ChangeFeedItem[]][] {
  const groups = new Map<string, ChangeFeedItem[]>();
  for (const item of items) {
    const day = localDay(item.at);
    const group = groups.get(day);
    if (group) group.push(item);
    else groups.set(day, [item]);
  }
  return [...groups];
}

interface BatchFilterProps {
  /** The batch the feed is filtered by, if any. */
  batchFilter: string | undefined;
  onShowBatch: (batchId: string) => void;
}

interface ChangeRowProps extends BatchFilterProps {
  change: ChangeFeedItem;
  meta: Meta;
  expanded: boolean;
  onToggle: () => void;
}

function BatchButton({ batchId, onShowBatch }: { batchId: string; onShowBatch: (batchId: string) => void }) {
  return (
    <Tooltip label="Show all changes of this batch">
      <ActionIcon
        size="xs"
        aria-label={`Show all changes of batch ${batchId}`}
        onClick={() => {
          onShowBatch(batchId);
        }}
      >
        <IconStack2 size={12} />
      </ActionIcon>
    </Tooltip>
  );
}

function ChangeRow({ change, meta, expanded, onToggle, batchFilter, onShowBatch }: ChangeRowProps) {
  const detailsId = `change-${change.id}-diff`;
  return (
    <>
      <Table.Tr>
        <Table.Td className={classes.cell}>
          <ActionIcon
            size="sm"
            aria-expanded={expanded}
            aria-controls={expanded ? detailsId : undefined}
            aria-label={`${expanded ? 'Hide' : 'Show'} the changes of ${change.entity_label} v${change.version}`}
            onClick={onToggle}
          >
            {expanded ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
          </ActionIcon>
        </Table.Td>
        <Table.Td className={classes.cell}>
          <TimeOfDay value={change.at} />
        </Table.Td>
        <Table.Td className={classes.cell}>
          <bdi>{change.author}</bdi>
        </Table.Td>
        <Table.Td className={classes.cell}>
          <span className={classes.chips}>
            <ChannelBadge channel={change.channel} />
            <ActionBadge action={change.action} />
            {change.batch_id !== null && change.batch_id !== batchFilter && (
              <BatchButton batchId={change.batch_id} onShowBatch={onShowBatch} />
            )}
          </span>
        </Table.Td>
        <Table.Td className={classes.cell}>
          <Text span size="xs" c="dimmed">
            {recordTypeLabel(meta, change.entity_type)}
          </Text>{' '}
          <TargetLink target={changeTarget(change)} label={change.entity_label} />
        </Table.Td>
        <Table.Td className={classes.cell}>
          v{change.version}
          {change.restored_from_version !== null && (
            <Text span size="xs" c="dimmed">
              {' '}
              from v{change.restored_from_version}
            </Text>
          )}
        </Table.Td>
        <Table.Td className={classes.cell}>
          <ChangedFieldChips fields={change.changed_fields} labels={recordFieldLabels(meta, change.entity_type)} />
        </Table.Td>
        <Table.Td className={`${classes.cell} ${classes.note}`}>{change.note}</Table.Td>
      </Table.Tr>
      {expanded && (
        <Table.Tr id={detailsId}>
          <Table.Td colSpan={COLUMNS} className={classes.details}>
            <RevisionDiffPanel revisionId={change.id} meta={meta} />
          </Table.Td>
        </Table.Tr>
      )}
    </>
  );
}

interface ChangeFeedTableProps extends BatchFilterProps {
  items: readonly ChangeFeedItem[];
  meta: Meta;
}

export function ChangeFeedTable({ items, meta, batchFilter, onShowBatch }: ChangeFeedTableProps) {
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());
  const toggle = (id: number) => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  };

  return (
    <Table.ScrollContainer minWidth={900}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={36}>
              <VisuallyHidden>Details</VisuallyHidden>
            </Table.Th>
            <Table.Th w={60}>Time</Table.Th>
            <Table.Th w={140}>Author</Table.Th>
            <Table.Th w={150}>Change</Table.Th>
            <Table.Th>Record</Table.Th>
            <Table.Th w={90}>Version</Table.Th>
            <Table.Th>Changed fields</Table.Th>
            <Table.Th>Note</Table.Th>
          </Table.Tr>
        </Table.Thead>
        {groupByDay(items).map(([day, changes]) => (
          <Table.Tbody key={day}>
            <Table.Tr>
              <Table.Th colSpan={COLUMNS} scope="rowgroup" className={classes.dayHeader}>
                <time dateTime={day}>{day}</time> · {dayjs(day).format('dddd')}
              </Table.Th>
            </Table.Tr>
            {changes.map((change) => (
              <ChangeRow
                key={change.id}
                change={change}
                meta={meta}
                expanded={expanded.has(change.id)}
                onToggle={() => {
                  toggle(change.id);
                }}
                batchFilter={batchFilter}
                onShowBatch={onShowBatch}
              />
            ))}
          </Table.Tbody>
        ))}
      </Table>
    </Table.ScrollContainer>
  );
}
