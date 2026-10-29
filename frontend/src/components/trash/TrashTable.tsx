// Deleted records of one trash tab (docs/UI.md §5): label, deletion time and
// author, "deleted together with n others" for cascades, the deletion note,
// and Undelete.
import { Table, Text, VisuallyHidden } from '@mantine/core';
import { IconRestore } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import { pluralize } from '../../lib/format';
import { Timestamp } from '../Timestamp';
import { WriteButton } from '../WriteButton';
import type { DeleteInfo } from './delete-info';
import classes from './trash.module.css';

interface TrashRowData {
  id: string;
  /** Plain label, for the Undelete button's accessible name. */
  label: string;
  /** The label as shown, usually a link. */
  record: ReactNode;
  deletedAt: string | null;
  deletedBy: string | null;
  info: DeleteInfo | undefined;
  onUndelete: () => void;
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
            <Table.Th w={150}>By</Table.Th>
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
              <Table.Td className={classes.cell}>{row.record}</Table.Td>
              <Table.Td className={classes.cell}>
                <Timestamp value={row.deletedAt} />
              </Table.Td>
              <Table.Td className={classes.cell}>
                <bdi>{row.deletedBy}</bdi>
              </Table.Td>
              <Table.Td className={classes.cell}>
                <DeletedTogether info={row.info} />
              </Table.Td>
              <Table.Td className={`${classes.cell} ${classes.note}`}>{row.info?.note}</Table.Td>
              <Table.Td className={classes.cell}>
                <WriteButton
                  variant="light"
                  leftSection={<IconRestore size={14} />}
                  aria-label={`Undelete ${row.label}`}
                  onClick={row.onUndelete}
                >
                  Undelete
                </WriteButton>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
