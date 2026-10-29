// Comment threads of the Comments page (docs/UI.md §5), one row per thread:
// an excerpt of the root comment, subject, field, status, who started it,
// replies and last activity. A row opens the subject's page with the thread
// open (vocabulary terms: the Codebook page).
import { Badge, Group, Table, Text } from '@mantine/core';
import type { MouseEvent } from 'react';

import type { Comment, CommentFeedItem, Meta } from '../../api/types';
import { Timestamp } from '../Timestamp';
import classes from './changes.module.css';
import { commentExcerpt } from './comment-text';
import { recordFields, recordTypeLabel } from './record-labels';
import { pageTarget, threadTarget } from './targets';
import { TargetLink } from './TargetLink';
import { useOpenTarget } from './useOpenTarget';

function StatusBadge({ root }: { root: Comment }) {
  if (root.deleted_at) {
    return (
      <Badge size="sm" variant="light" color="red">
        deleted
      </Badge>
    );
  }
  return (
    <Badge size="sm" variant="light" color={root.status === 'resolved' ? 'green' : 'yellow'}>
      {root.status ?? 'open'}
    </Badge>
  );
}

function FieldName({ meta, root }: { meta: Meta; root: Comment }) {
  if (root.field === null) {
    return (
      <Text span size="sm" c="dimmed">
        whole record
      </Text>
    );
  }
  const field = recordFields(meta, root.subject_type).find((candidate) => candidate.name === root.field);
  return <span title={root.field}>{field?.label ?? root.field}</span>;
}

/** Clicks on links and buttons inside a row act on those, not on the row. */
const isInteractive = (target: EventTarget): boolean =>
  target instanceof Element && target.closest('a, button, input, label') !== null;

export function CommentFeedTable({ items, meta }: { items: readonly CommentFeedItem[]; meta: Meta }) {
  const open = useOpenTarget();
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Thread</Table.Th>
            <Table.Th>Subject</Table.Th>
            <Table.Th>Field</Table.Th>
            <Table.Th w={90}>Status</Table.Th>
            <Table.Th>Started</Table.Th>
            <Table.Th w={70} ta="right">
              Replies
            </Table.Th>
            <Table.Th w={140}>Last activity</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map(({ root, reply_count: replies, last_activity_at: lastActivity }) => {
            const target = threadTarget(root.subject_type, root.subject_id, root.id);
            const onClick = (event: MouseEvent) => {
              if (target && !isInteractive(event.target)) open(target);
            };
            return (
              <Table.Tr key={root.id} className={target ? classes.row : undefined} onClick={onClick}>
                <Table.Td className={`${classes.cell} ${classes.excerpt}`}>
                  <TargetLink target={target} label={commentExcerpt(root.body_md)} />
                </Table.Td>
                <Table.Td className={classes.cell}>
                  <Text span size="xs" c="dimmed">
                    {recordTypeLabel(meta, root.subject_type)}
                  </Text>{' '}
                  <TargetLink target={pageTarget(root.subject_type, root.subject_id)} label={root.subject_label} />
                </Table.Td>
                <Table.Td className={classes.cell}>
                  <FieldName meta={meta} root={root} />
                </Table.Td>
                <Table.Td className={classes.cell}>
                  <StatusBadge root={root} />
                </Table.Td>
                <Table.Td className={classes.cell}>
                  <Group gap={6} wrap="wrap">
                    <bdi>{root.created_by}</bdi>
                    <Text span size="xs" c="dimmed">
                      <Timestamp value={root.created_at} />
                    </Text>
                  </Group>
                </Table.Td>
                <Table.Td className={classes.cell} ta="right">
                  {replies}
                </Table.Td>
                <Table.Td className={classes.cell}>
                  <Timestamp value={lastActivity} />
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
