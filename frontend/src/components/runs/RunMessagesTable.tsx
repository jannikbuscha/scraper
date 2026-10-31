// Messages of a run (docs/UI.md §8.3): time, level, code, message, URL,
// snapshot and record. Messages are plain text. Times, levels, codes and
// snapshot links stay on one line; messages and URLs wrap (a URL at any
// character), so a long URL never pushes the other columns aside.
import { Badge, Table, Text } from '@mantine/core';
import { IconAlertCircle, IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react';

import type { MessageLevel, RunMessage } from '../../api/acquisition-types';
import type { Refs } from '../../api/types';
import { EntityLink } from '../EntityLink';
import { ExternalLink } from '../ExternalLink';
import { SnapshotLink } from '../SnapshotLink';
import { Timestamp } from '../Timestamp';
import { MESSAGE_LEVEL_COLORS, TABLE_BADGE_MIN_WIDTH } from './run-labels';
import classes from './runs.module.css';

function LevelIcon({ level }: { level: MessageLevel }) {
  const props = { size: 16, color: `var(--mantine-color-${MESSAGE_LEVEL_COLORS[level]}-6)`, 'aria-hidden': true } as const;
  const icon =
    level === 'error' ? (
      <IconAlertCircle {...props} />
    ) : level === 'warning' ? (
      <IconAlertTriangle {...props} />
    ) : (
      <IconInfoCircle {...props} />
    );
  return (
    <Badge size="xs" variant="light" color={MESSAGE_LEVEL_COLORS[level]} leftSection={icon} miw={TABLE_BADGE_MIN_WIDTH}>
      {level}
    </Badge>
  );
}

const nowrap = `${classes.cell} ${classes.nowrap}`;

export function RunMessagesTable({ messages, refs }: { messages: readonly RunMessage[]; refs: Refs }) {
  if (messages.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No messages.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={130}>Time</Table.Th>
            <Table.Th w={100}>Level</Table.Th>
            <Table.Th w={170}>Code</Table.Th>
            <Table.Th>Message</Table.Th>
            <Table.Th>URL</Table.Th>
            <Table.Th w={90}>Snapshot</Table.Th>
            <Table.Th>Record</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {messages.map((message) => {
            const ref = message.subject_id ? refs[message.subject_id] : undefined;
            return (
              <Table.Tr key={message.id}>
                <Table.Td className={nowrap}>
                  <Timestamp value={message.at} />
                </Table.Td>
                <Table.Td className={nowrap}>
                  <LevelIcon level={message.level} />
                </Table.Td>
                <Table.Td className={nowrap}>
                  <code>{message.code}</code>
                </Table.Td>
                <Table.Td className={`${classes.cell} ${classes.message}`}>{message.message}</Table.Td>
                <Table.Td className={classes.cell}>{message.url && <ExternalLink url={message.url} wrap />}</Table.Td>
                <Table.Td className={nowrap}>
                  {message.raw_snapshot_id && <SnapshotLink id={message.raw_snapshot_id} />}
                </Table.Td>
                <Table.Td className={classes.cell}>
                  {message.subject_id && (
                    <EntityLink id={message.subject_id} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
