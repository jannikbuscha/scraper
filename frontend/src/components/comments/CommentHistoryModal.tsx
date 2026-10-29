// The revision list of a comment, opened from its "edited" label (docs/UI.md
// §4.3): word diffs of each revision and "Restore this version" with an
// optional note; a conflict is confirmed again (docs/UI.md §1.3).
import { Alert, Button, Group, Loader, Modal, Paper, Stack, Text, Textarea } from '@mantine/core';
import { IconRestore } from '@tabler/icons-react';
import { useState } from 'react';

import { isApiError, isConflictError } from '../../api/client';
import { useRestoreComment, useRevision, useRevisions } from '../../api/queries';
import type { Comment, ConflictPayload } from '../../api/types';
import { syntheticField } from '../../lib/format';
import { ChangedMeanwhileAlert } from '../history/ChangedMeanwhileAlert';
import { errorMessage, ErrorAlert, notifySuccess } from '../feedback';
import { DiffView } from '../history/DiffView';
import { RevisionList } from '../history/RevisionList';
import { WriteButton } from '../WriteButton';
import { CommentChangedNotice } from './CommentChangedNotice';

/** The tracked fields of a comment (docs/DATA_MODEL.md §6.6), for diff labels. */
const COMMENT_FIELDS = [
  syntheticField('body_md', 'text', 'Text'),
  syntheticField('status', 'string', 'Status'),
  syntheticField('resolved_by', 'string', 'Resolved by'),
  syntheticField('resolved_at', 'datetime', 'Resolved at'),
];

const FIELD_LABELS = Object.fromEntries(COMMENT_FIELDS.map((field) => [field.name, field.label]));

interface CommentHistoryModalProps {
  comment: Comment;
  opened: boolean;
  maxNoteChars: number;
  onClose: () => void;
}

export function CommentHistoryModal({ comment, opened, maxNoteChars, onClose }: CommentHistoryModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} size="xl" title="Comment history">
      {opened && <CommentHistory comment={comment} maxNoteChars={maxNoteChars} />}
    </Modal>
  );
}

function CommentHistory({ comment, maxNoteChars }: { comment: Comment; maxNoteChars: number }) {
  const revisions = useRevisions('comment', comment.id, 1, 100);
  const [selected, setSelected] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);
  const items = revisions.data?.items ?? [];
  const shown = selected ?? items[0]?.version ?? null;
  const revision = useRevision('comment', comment.id, shown);

  if (revisions.isPending) return <Loader size="sm" />;
  if (revisions.isError) {
    return (
      <ErrorAlert title="Could not load the history" error={revisions.error} onRetry={() => void revisions.refetch()} />
    );
  }

  return (
    <Stack gap="sm">
      <RevisionList
        revisions={items}
        fieldLabels={FIELD_LABELS}
        currentVersion={comment.version}
        selectedVersion={shown}
        onSelect={(row) => {
          setSelected(row.version);
        }}
        renderActions={(row) => (
          <WriteButton
            size="compact-xs"
            variant="subtle"
            leftSection={<IconRestore size={12} />}
            disabled={row.version === comment.version || comment.deleted_at !== null}
            aria-label={`Restore version ${row.version} of the comment`}
            onClick={() => {
              setRestoring(row.version);
            }}
          >
            Restore
          </WriteButton>
        )}
      />
      {restoring !== null && (
        <RestoreCommentForm
          key={restoring}
          comment={comment}
          version={restoring}
          maxNoteChars={maxNoteChars}
          onDone={() => {
            setRestoring(null);
          }}
        />
      )}
      <Paper withBorder p="sm">
        {revision.isPending && shown !== null && <Loader size="xs" />}
        {revision.data && (
          <Stack gap="xs">
            <Text size="sm" fw={600}>
              Changes in v{revision.data.revision.version}
            </Text>
            <DiffView diff={revision.data.revision.diff} fields={COMMENT_FIELDS} refs={revision.data.refs} />
          </Stack>
        )}
      </Paper>
    </Stack>
  );
}

function RestoreCommentForm({
  comment,
  version,
  maxNoteChars,
  onDone,
}: {
  comment: Comment;
  version: number;
  maxNoteChars: number;
  onDone: () => void;
}) {
  const restore = useRestoreComment();
  const [note, setNote] = useState('');
  const [expected, setExpected] = useState(comment.version);
  const [conflict, setConflict] = useState<ConflictPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);

  const submit = async () => {
    setError(null);
    try {
      const result = await restore.mutateAsync({
        id: comment.id,
        expected_version: expected,
        version,
        note: note.trim() || null,
      });
      notifySuccess(`Restored version ${version} of the comment as version ${result.comment.version}.`);
      onDone();
    } catch (failure) {
      if (isConflictError(failure) && failure.payload.current_state.deleted_at === null) {
        setConflict(failure.payload);
        setExpected(failure.payload.current_version);
      } else if (isConflictError(failure) || isApiError(failure, 'entity_deleted')) setStale(true);
      else setError(errorMessage(failure));
    }
  };

  if (stale) return <CommentChangedNotice comment={comment} onReloaded={onDone} />;

  return (
    <Paper withBorder p="sm">
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          Restore version {version}
        </Text>
        {conflict && (
          <ChangedMeanwhileAlert
            revisions={conflict.intervening}
            fieldLabels={FIELD_LABELS}
            question="Restore it anyway?"
          />
        )}
        <Textarea
          label="Note (optional)"
          autosize
          minRows={1}
          maxLength={maxNoteChars}
          value={note}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button loading={restore.isPending} onClick={() => void submit()}>
            {conflict ? 'Restore anyway' : 'Restore'}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
