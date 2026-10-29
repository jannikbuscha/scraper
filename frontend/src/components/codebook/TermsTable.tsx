// The terms of one vocabulary (docs/UI.md §5): code, labels, definition with
// include/exclude notes and examples, active state and replacement, usage
// count, sort order, attributes, open comments (opening the term's comments
// panel), and the actions Edit, History and Deactivate.
import { ActionIcon, Badge, Button, Group, Stack, Table, Text, Tooltip } from '@mantine/core';
import { IconBan, IconHistory, IconMessage, IconPencil } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import type { Vocabulary, VocabTerm } from '../../api/types';
import classes from './codebook.module.css';
import { TermAttributes } from './TermAttributes';
import { isFixedTerm } from './term-form';

export type TermAction = 'edit' | 'history' | 'comments' | 'deactivate';

type OnTermAction = (action: TermAction, term: VocabTerm) => void;

interface TermsTableProps {
  vocabulary: Vocabulary;
  /** The term whose comments are open, highlighted. */
  selectedTermId: string | null;
  onAction: OnTermAction;
}

const count = new Intl.NumberFormat('en-US');

function Notes({ term }: { term: VocabTerm }) {
  const notes: [string, string | null][] = [
    ['Include', term.include_note],
    ['Exclude', term.exclude_note],
    ['Examples', term.examples],
  ];
  return (
    <Stack gap={2}>
      {term.definition && <div className={classes.text}>{term.definition}</div>}
      {notes.map(([label, text]) =>
        text ? (
          <Text key={label} size="xs" c="dimmed" className={classes.text}>
            {label}: {text}
          </Text>
        ) : null,
      )}
    </Stack>
  );
}

function ActiveState({ term }: { term: VocabTerm }) {
  if (term.active) return <Text span size="sm">active</Text>;
  return (
    <Stack gap={2}>
      <Badge size="sm" variant="light" color="gray">
        inactive
      </Badge>
      {term.replaced_by && (
        <Text size="xs" c="dimmed">
          replaced by <code>{term.replaced_by}</code>
        </Text>
      )}
    </Stack>
  );
}

interface RowActionProps {
  label: string;
  icon: ReactNode;
  onClick: () => void;
  /** Why the action is not available; the action is enabled without one. */
  disabledReason?: string | undefined;
}

function RowAction({ label, icon, onClick, disabledReason }: RowActionProps) {
  return (
    <Tooltip label={disabledReason ?? label}>
      <ActionIcon size="sm" aria-label={label} disabled={disabledReason !== undefined} onClick={onClick}>
        {icon}
      </ActionIcon>
    </Tooltip>
  );
}

interface TermRowProps {
  term: VocabTerm;
  vocabulary: Vocabulary;
  selected: boolean;
  onAction: OnTermAction;
}

function TermRow({ term, vocabulary, selected, onAction }: TermRowProps) {
  const deactivateReason = isFixedTerm(vocabulary, term.attributes)
    ? 'Fixed code: program logic uses it, so it cannot be deactivated.'
    : term.active
      ? undefined
      : 'Already inactive.';
  const className = [selected && classes.selected, !term.active && classes.inactive].filter(Boolean).join(' ');

  return (
    <Table.Tr className={className || undefined} aria-selected={selected}>
      <Table.Td className={classes.cell}>
        <code>{term.code}</code>
      </Table.Td>
      <Table.Td className={classes.cell}>
        <bdi>{term.label_en}</bdi>
        {term.label_uk && (
          <Text size="xs" c="dimmed" lang="uk">
            <bdi>{term.label_uk}</bdi>
          </Text>
        )}
      </Table.Td>
      <Table.Td className={classes.cell}>
        <Notes term={term} />
      </Table.Td>
      <Table.Td className={classes.cell}>
        <ActiveState term={term} />
      </Table.Td>
      <Table.Td className={classes.cell} ta="right">
        <span title="Non-deleted records whose fields use this code">{count.format(term.usage_count)}</span>
      </Table.Td>
      <Table.Td className={classes.cell} ta="right">
        {term.sort_order ?? '—'}
      </Table.Td>
      <Table.Td className={classes.cell}>
        <TermAttributes attributes={term.attributes} />
      </Table.Td>
      <Table.Td className={classes.cell}>
        <Button
          variant={term.open_comments > 0 ? 'light' : 'subtle'}
          color={term.open_comments > 0 ? 'yellow' : 'gray'}
          size="compact-xs"
          leftSection={<IconMessage size={14} />}
          aria-label={`Comments on ${term.code} (${term.open_comments} open)`}
          onClick={() => {
            onAction('comments', term);
          }}
        >
          {term.open_comments}
        </Button>
      </Table.Td>
      <Table.Td className={classes.cell}>
        <Group gap={2} wrap="nowrap">
          <RowAction
            label={`Edit ${term.code}`}
            icon={<IconPencil size={15} />}
            onClick={() => {
              onAction('edit', term);
            }}
          />
          <RowAction
            label={`History of ${term.code}`}
            icon={<IconHistory size={15} />}
            onClick={() => {
              onAction('history', term);
            }}
          />
          <RowAction
            label={`Deactivate ${term.code}`}
            icon={<IconBan size={15} />}
            disabledReason={deactivateReason}
            onClick={() => {
              onAction('deactivate', term);
            }}
          />
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}

export function TermsTable({ vocabulary, selectedTermId, onAction }: TermsTableProps) {
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Code</Table.Th>
            <Table.Th>Label</Table.Th>
            <Table.Th>Definition</Table.Th>
            <Table.Th w={110}>State</Table.Th>
            <Table.Th w={70} ta="right">
              Usage
            </Table.Th>
            <Table.Th w={60} ta="right">
              Order
            </Table.Th>
            <Table.Th>Attributes</Table.Th>
            <Table.Th w={90}>Open comments</Table.Th>
            <Table.Th w={100}>Actions</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {vocabulary.terms.map((term) => (
            <TermRow
              key={term.id}
              term={term}
              vocabulary={vocabulary}
              selected={term.id === selectedTermId}
              onAction={onAction}
            />
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
