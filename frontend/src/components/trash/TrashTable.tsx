// Deleted records of one trash tab (docs/UI.md §5): label, deletion time,
// "deleted together with n others" for cascades, the deletion note, and
// Undelete; a merged project or service reads "Merged into …" and offers
// Unmerge instead (§8.7).
import { Button, Table, Text, VisuallyHidden } from '@mantine/core';
import { IconGitMerge, IconRestore } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import { pluralize } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { Timestamp } from '../Timestamp';
import type { DeleteInfo } from './delete-info';
import classes from './trash.module.css';

interface TrashRowData {
  id: string;
  /** Plain label, for the Undelete button's accessible name. */
  label: string;
  /** The label as shown, usually a link. */
  record: ReactNode;
  deletedAt: string | null;
  info: DeleteInfo | undefined;
  onUndelete: () => void;
  /** A merged record: its survivor, and Unmerge instead of Undelete. */
  merged?: { survivorId: string; onUnmerge: () => void } | undefined;
}

function DeletedTogether({ info }: { info: DeleteInfo | undefined }) {
  if (info === undefined) return null;
  if (info.others === 0) {
    return info.exact ? (
      <Text span size="sm" c="dimmed">
        —
      </Text>
    ) : null;
  }
  return <>with {info.exact ? pluralize(info.others, 'other') : `${pluralize(info.others, 'other')} or more`}</>;
}

export function TrashTable({ rows }: { rows: readonly TrashRowData[] }) {
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Record</Table.Th>
            <Table.Th w={140}>Deleted</Table.Th>
            <Table.Th w={170}>Deleted together</Table.Th>
            <Table.Th>Note</Table.Th>
            <Table.Th w={120}>
              <VisuallyHidden>Actions</VisuallyHidden>
            </Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td className={classes.cell}>
                {row.record}
                {row.merged && (
                  <Text span size="sm" c="dimmed">
                    {' '}
                    · Merged into <EntityLink id={row.merged.survivorId} />
                  </Text>
                )}
              </Table.Td>
              <Table.Td className={classes.cell}>
                <Timestamp value={row.deletedAt} />
              </Table.Td>
              <Table.Td className={classes.cell}>
                <DeletedTogether info={row.info} />
              </Table.Td>
              <Table.Td className={`${classes.cell} ${classes.note}`}>{row.info?.note}</Table.Td>
              <Table.Td className={classes.cell}>
                {row.merged ? (
                  <Button
                    variant="light"
                    color="grape"
                    leftSection={<IconGitMerge size={14} />}
                    aria-label={`Unmerge ${row.label}`}
                    onClick={row.merged.onUnmerge}
                  >
                    Unmerge…
                  </Button>
                ) : (
                  <Button
                    variant="light"
                    leftSection={<IconRestore size={14} />}
                    aria-label={`Undelete ${row.label}`}
                    onClick={row.onUndelete}
                  >
                    Undelete
                  </Button>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
