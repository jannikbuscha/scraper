// Decisions with a dialog (docs/UI.md §8.2): Reject and Not duplicates (a
// note is required), Link to existing (a lookup restricted to the proposal's
// type) and Mark as duplicate (documents: which of the two is the duplicate).
import { Alert, Button, Group, Modal, Radio, Stack, Text, Textarea } from '@mantine/core';
import { IconExternalLink } from '@tabler/icons-react';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import type { AcceptResponse, Proposal } from '../../api/acquisition-types';
import { invalidState, isApiError } from '../../api/client';
import { useAcceptProposal, useRejectProposal } from '../../api/proposals';
import type { Refs } from '../../api/types';
import { DETAIL_PATHS } from '../../lib/entity';
import { AnchorLink } from '../AnchorLink';
import { errorMessage } from '../feedback';
import { RefSelect } from '../fields/inputs/RefSelect';

/** A refused decision in words. */
export function decisionError(error: unknown): string {
  const state = invalidState(error);
  if (state) return `This proposal is no longer open (${state}).`;
  if (isApiError(error, 'entity_deleted')) return 'The record this proposal concerns is deleted; undelete it first.';
  return errorMessage(error);
}

interface DialogFrameProps {
  submitLabel: string;
  submitColor?: string;
  pending: boolean;
  disabled?: boolean;
  error: ReactNode;
  onSubmit: () => void;
  onCancel: () => void;
  children: ReactNode;
}

function DialogForm({ submitLabel, submitColor, pending, disabled = false, error, onSubmit, onCancel, children }: DialogFrameProps) {
  return (
    <form
      onSubmit={(event: SubmitEvent) => {
        event.preventDefault();
        onSubmit();
      }}
      noValidate
    >
      <Stack gap="sm">
        {children}
        {error && (
          <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" color={submitColor} loading={pending} disabled={disabled}>
            {submitLabel}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

/** Reject; for a duplicate pair the same rejection is worded "Not duplicates". */
interface RejectModalProps {
  proposal: Proposal | null;
  maxNoteChars: number;
  onClose: () => void;
  onRejected: (proposal: Proposal) => void;
}

export function RejectModal({ proposal, maxNoteChars, onClose, onRejected }: RejectModalProps) {
  const duplicate = proposal?.kind === 'possible_duplicate';
  return (
    <Modal opened={proposal !== null} onClose={onClose} title={duplicate ? 'Not duplicates' : 'Reject proposal'}>
      {proposal && <RejectForm key={proposal.id} proposal={proposal} maxNoteChars={maxNoteChars} onDone={onClose} onRejected={onRejected} />}
    </Modal>
  );
}

function RejectForm({ proposal, maxNoteChars, onDone, onRejected }: Omit<RejectModalProps, 'onClose'> & { proposal: Proposal; onDone: () => void }) {
  const reject = useRejectProposal();
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const duplicate = proposal.kind === 'possible_duplicate';
  const missing = note.trim() === '';
  return (
    <DialogForm
      submitLabel={duplicate ? 'Not duplicates' : 'Reject'}
      submitColor="red"
      pending={reject.isPending}
      disabled={missing}
      error={error}
      onCancel={onDone}
      onSubmit={() => {
        if (missing) return;
        reject.mutateAsync({ proposal, note: note.trim() }).then(
          () => {
            onRejected(proposal);
            onDone();
          },
          (caught: unknown) => {
            setError(decisionError(caught));
          },
        );
      }}
    >
      <Text size="sm">
        {duplicate
          ? 'The two records stay as they are, and the pair is not proposed again.'
          : 'Nothing is written, and the same value is not proposed again.'}
      </Text>
      <Textarea
        label="Reason"
        description="Required: why the proposal is rejected."
        required
        autosize
        minRows={2}
        maxLength={maxNoteChars}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
    </DialogForm>
  );
}

interface AcceptDialogProps {
  proposal: Proposal | null;
  refs: Refs;
  maxNoteChars: number;
  onClose: () => void;
  onAccepted: (proposal: Proposal, response: AcceptResponse) => void;
}

/** Link to existing: the source entry is bound to a chosen record instead of creating one. */
export function LinkExistingModal({ proposal, initialMatch, ...rest }: AcceptDialogProps & { initialMatch: string | null }) {
  return (
    <Modal opened={proposal !== null} onClose={rest.onClose} title="Link to an existing record">
      {proposal && <LinkForm key={proposal.id} proposal={proposal} initialMatch={initialMatch} {...rest} />}
    </Modal>
  );
}

function LinkForm({
  proposal,
  initialMatch,
  refs,
  maxNoteChars,
  onClose,
  onAccepted,
}: Omit<AcceptDialogProps, 'proposal'> & { proposal: Proposal; initialMatch: string | null }) {
  const accept = useAcceptProposal();
  const [match, setMatch] = useState<string | null>(initialMatch);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  return (
    <DialogForm
      submitLabel="Link"
      pending={accept.isPending}
      disabled={match === null}
      error={error}
      onCancel={onClose}
      onSubmit={() => {
        if (match === null) return;
        accept.mutateAsync({ proposal, match_id: match, note: note.trim() || null }).then(
          (response) => {
            onAccepted(proposal, response);
            onClose();
          },
          (caught: unknown) => {
            setError(decisionError(caught));
          },
        );
      }}
    >
      <Text size="sm">
        The source entry is bound to the chosen record; nothing else is written, and later runs update that record.
      </Text>
      <RefSelect
        label="Record"
        types={[proposal.entity_type]}
        value={match}
        currentRef={match ? refs[match] : undefined}
        required
        onChange={setMatch}
      />
      <Textarea
        label="Decision note (optional)"
        autosize
        minRows={2}
        maxLength={maxNoteChars}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
    </DialogForm>
  );
}

/** Documents: the chosen one is screened out as a duplicate of the other. */
export function MarkDuplicateModal(props: AcceptDialogProps) {
  return (
    <Modal opened={props.proposal !== null} onClose={props.onClose} title="Mark as duplicate">
      {props.proposal && <MarkDuplicateForm key={props.proposal.id} {...props} proposal={props.proposal} />}
    </Modal>
  );
}

function MarkDuplicateForm({ proposal, refs, maxNoteChars, onClose, onAccepted }: AcceptDialogProps & { proposal: Proposal }) {
  const accept = useAcceptProposal();
  const [duplicate, setDuplicate] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const pair = [proposal.subject_id, proposal.related_id].filter((id): id is string => id !== null);
  return (
    <DialogForm
      submitLabel="Mark as duplicate"
      pending={accept.isPending}
      disabled={duplicate === null}
      error={error}
      onCancel={onClose}
      onSubmit={() => {
        if (duplicate === null) return;
        accept.mutateAsync({ proposal, values: { duplicate_id: duplicate }, note: note.trim() || null }).then(
          (response) => {
            onAccepted(proposal, response);
            onClose();
          },
          (caught: unknown) => {
            setError(decisionError(caught));
          },
        );
      }}
    >
      <Radio.Group
        label="Which document is the duplicate?"
        description="It is screened out (excluded, reason: duplicate) with a note naming the other one."
        value={duplicate}
        onChange={setDuplicate}
      >
        <Stack gap={6} mt={6}>
          {pair.map((id) => {
            const label = refs[id]?.label ?? id;
            // The label only chooses; the document opens from its own link, in a new tab, so the dialog stays.
            return (
              <Group key={id} gap={6} wrap="nowrap" align="center">
                <Radio value={id} label={<bdi>{label}</bdi>} />
                <AnchorLink
                  to={DETAIL_PATHS.document}
                  params={{ id }}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Open ${label} in a new tab`}
                  title="Open in a new tab"
                  display="inline-flex"
                >
                  <IconExternalLink size={14} aria-hidden />
                </AnchorLink>
              </Group>
            );
          })}
        </Stack>
      </Radio.Group>
      <Textarea
        label="Decision note (optional)"
        autosize
        minRows={2}
        maxLength={maxNoteChars}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
        }}
      />
    </DialogForm>
  );
}
