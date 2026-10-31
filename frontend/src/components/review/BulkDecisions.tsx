// Bulk decisions of the review inbox (docs/UI.md §8.2): "Accept selected"
// (confirmed with the count) and "Reject selected…" (a note); the summary
// counts the results and lists the proposals left open to decide one by one
// (new projects and duplicates need values; stale ones changed since).
import { Alert, Badge, Button, Group, List, Modal, Stack, Text, Textarea, Title } from '@mantine/core';
import { IconCheck, IconX } from '@tabler/icons-react';
import { useState } from 'react';

import type { BulkDecisionResponse, BulkDecisionStatus, Proposal } from '../../api/acquisition-types';
import { useBulkDecision } from '../../api/proposals';
import type { Refs } from '../../api/types';
import { pluralize } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { errorMessage } from '../feedback';
import { BULK_STATUS_LABELS, KIND_LABELS } from './proposal-labels';

const STATUS_ORDER: readonly BulkDecisionStatus[] = ['accepted', 'rejected', 'superseded', 'needs_values', 'stale', 'error'];
const STATUS_COLORS: Record<BulkDecisionStatus, string> = {
  accepted: 'green',
  rejected: 'red',
  superseded: 'gray',
  needs_values: 'orange',
  stale: 'orange',
  error: 'red',
};

interface BulkBarProps {
  selected: readonly Proposal[];
  onAccept: () => void;
  onReject: () => void;
  onClear: () => void;
}

export function BulkBar({ selected, onAccept, onReject, onClear }: BulkBarProps) {
  if (selected.length === 0) return null;
  return (
    <Group gap="xs" role="toolbar" aria-label="Selected proposals">
      <Text size="sm" fw={500}>
        {pluralize(selected.length, 'proposal')} selected
      </Text>
      <Button size="xs" leftSection={<IconCheck size={14} />} onClick={onAccept}>
        Accept selected
      </Button>
      <Button size="xs" variant="light" color="red" leftSection={<IconX size={14} />} onClick={onReject}>
        Reject selected…
      </Button>
      <Button size="xs" variant="subtle" color="gray" onClick={onClear}>
        Clear selection
      </Button>
    </Group>
  );
}

interface BulkDecisionModalProps {
  action: 'accept' | 'reject' | null;
  proposals: readonly Proposal[];
  refs: Refs;
  maxNoteChars: number;
  onClose: () => void;
  /** The decisions were sent (the selection can be cleared). */
  onDecided: () => void;
}

export function BulkDecisionModal({ action, proposals, refs, maxNoteChars, onClose, onDecided }: BulkDecisionModalProps) {
  return (
    <Modal
      opened={action !== null}
      onClose={onClose}
      title={action === 'reject' ? 'Reject the selected proposals' : 'Accept the selected proposals'}
      size="lg"
    >
      {action && (
        <BulkDecisionBody action={action} proposals={proposals} refs={refs} maxNoteChars={maxNoteChars} onClose={onClose} onDecided={onDecided} />
      )}
    </Modal>
  );
}

function BulkDecisionBody({
  action,
  proposals,
  refs,
  maxNoteChars,
  onClose,
  onDecided,
}: Omit<BulkDecisionModalProps, 'action'> & { action: 'accept' | 'reject' }) {
  const decide = useBulkDecision();
  const [note, setNote] = useState('');
  const [result, setResult] = useState<BulkDecisionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (result) return <BulkSummary result={result} proposals={proposals} refs={refs} onClose={onClose} />;

  const noteMissing = action === 'reject' && note.trim() === '';
  const submit = () => {
    setError(null);
    decide.mutateAsync({ proposals, action, note: note.trim() || null }).then(
      (response) => {
        setResult(response);
        onDecided();
      },
      (caught: unknown) => {
        setError(errorMessage(caught));
      },
    );
  };

  return (
    <Stack gap="sm">
      <Text size="sm">
        {action === 'accept'
          ? `Accept ${pluralize(proposals.length, 'proposal')}? Each is written on its own. New projects and duplicates need your values and stay open, as do field updates whose value changed since they were raised.`
          : `Reject ${pluralize(proposals.length, 'proposal')}? Nothing is written, and the same values are not proposed again.`}
      </Text>
      <Textarea
        label={action === 'reject' ? 'Reason' : 'Decision note (optional)'}
        required={action === 'reject'}
        autosize
        minRows={2}
        maxLength={maxNoteChars}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
      {error && (
        <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
          {error}
        </Alert>
      )}
      <Group justify="flex-end" gap="xs">
        <Button variant="default" onClick={onClose}>
          Cancel
        </Button>
        <Button color={action === 'reject' ? 'red' : undefined} loading={decide.isPending} disabled={noteMissing} onClick={submit}>
          {action === 'reject' ? `Reject ${proposals.length}` : `Accept ${proposals.length}`}
        </Button>
      </Group>
    </Stack>
  );
}

function BulkSummary({
  result,
  proposals,
  refs,
  onClose,
}: {
  result: BulkDecisionResponse;
  proposals: readonly Proposal[];
  refs: Refs;
  onClose: () => void;
}) {
  const counts = new Map<BulkDecisionStatus, number>();
  for (const entry of result.results) counts.set(entry.status, (counts.get(entry.status) ?? 0) + 1);
  const byId = new Map(proposals.map((proposal) => [proposal.id, proposal]));
  const listed = (status: BulkDecisionStatus) => result.results.filter((entry) => entry.status === status);
  const describe = (id: string) => {
    const proposal = byId.get(id);
    const subject = proposal?.subject_id;
    return (
      <>
        {proposal ? KIND_LABELS[proposal.kind] : 'Proposal'}
        {subject && (
          <>
            {' · '}
            <EntityLink id={subject} label={refs[subject]?.label} type={refs[subject]?.type} />
          </>
        )}
      </>
    );
  };
  return (
    <Stack gap="sm">
      <Group gap="xs" role="list" aria-label="Results per status">
        {STATUS_ORDER.filter((status) => (counts.get(status) ?? 0) > 0).map((status) => (
          <Badge key={status} role="listitem" variant="light" color={STATUS_COLORS[status]}>
            {BULK_STATUS_LABELS[status]}: {counts.get(status)}
          </Badge>
        ))}
      </Group>
      {(['needs_values', 'stale'] as const).map((status) =>
        listed(status).length > 0 ? (
          <Stack key={status} gap={4}>
            <Title order={4}>{BULK_STATUS_LABELS[status]}</Title>
            <List size="sm">
              {listed(status).map((entry) => (
                <List.Item key={entry.id}>{describe(entry.id)}</List.Item>
              ))}
            </List>
          </Stack>
        ) : null,
      )}
      {listed('error').length > 0 && (
        <Stack gap={4}>
          <Title order={4}>Errors (left open)</Title>
          <List size="sm">
            {listed('error').map((entry) => (
              <List.Item key={entry.id}>
                {describe(entry.id)}: {entry.error?.message ?? 'Unknown error.'}
              </List.Item>
            ))}
          </List>
        </Stack>
      )}
      <Group justify="flex-end">
        <Button onClick={onClose}>Close</Button>
      </Group>
    </Stack>
  );
}
