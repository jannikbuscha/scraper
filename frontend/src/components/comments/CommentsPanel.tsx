// The comments panel of the detail page (docs/UI.md §4.3): filters (open,
// resolved or all; field incl. entity-level only; show deleted), the composer
// with a field selector, and the threads. `thread=<id>` switches the status
// filter to "all" and scrolls to that thread.
import {
  Alert,
  Button,
  CloseButton,
  Group,
  Loader,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  Title,
} from '@mantine/core';
import { useEffect, useRef, useState } from 'react';

import { useCommentThreads } from '../../api/queries';
import type { CommentStatus, EntityTypeMeta, Item, Meta } from '../../api/types';
import { pick } from '../../lib/format';
import { ErrorAlert } from '../feedback';
import { commentFieldGroups, ENTITY_LEVEL, fieldLabelOf } from './comment-fields';
import { CommentComposer } from './CommentComposer';
import { CommentThreadView, threadElementId } from './CommentThreadView';

type StatusFilter = CommentStatus | 'all';
const STATUS_FILTERS: readonly StatusFilter[] = ['open', 'resolved', 'all'];

/** A request to start a comment, e.g. from a field's comment button. */
export interface CommentFocus {
  field: string | null;
  /** Increases with every request, so a repeated request is noticed. */
  key: number;
}

interface CommentsPanelProps {
  subject: Item;
  meta: Meta;
  typeMeta: EntityTypeMeta;
  /** `thread=<id>` from the URL. */
  threadId: string | null;
  focus: CommentFocus | null;
  onClose: () => void;
}

export function CommentsPanel({ subject, meta, typeMeta, threadId, focus, onClose }: CommentsPanelProps) {
  const [status, setStatus] = useState<StatusFilter>(threadId ? 'all' : 'open');
  const [fieldFilter, setFieldFilter] = useState<string | null>(focus?.field ?? null);
  const [showDeleted, setShowDeleted] = useState(false);
  const [composerField, setComposerField] = useState<string | null>(focus?.field ?? null);

  // A new thread link shows all statuses; a new focus request selects its field.
  const [seenThread, setSeenThread] = useState(threadId);
  if (threadId !== seenThread) {
    setSeenThread(threadId);
    if (threadId) setStatus('all');
  }
  const [seenFocus, setSeenFocus] = useState(focus?.key);
  if (focus && focus.key !== seenFocus) {
    setSeenFocus(focus.key);
    setFieldFilter(focus.field);
    setComposerField(focus.field);
  }

  const threads = useCommentThreads(subject.id, {
    status: status === 'all' ? undefined : status,
    field: fieldFilter ?? undefined,
    deleted: showDeleted ? 'include' : undefined,
  });
  const loaded = threads.data?.threads;
  const linkedShown = threadId !== null && (loaded ?? []).some((thread) => thread.root.id === threadId);

  // Scroll to the linked thread once it is shown (once per link, not after every reload).
  const scrolledTo = useRef<string | null>(null);
  useEffect(() => {
    if (!threadId || !loaded || scrolledTo.current === threadId) return;
    const element = document.getElementById(threadElementId(threadId));
    if (!element) return;
    element.scrollIntoView({ block: 'nearest' });
    scrolledTo.current = threadId;
  }, [threadId, loaded]);

  const fieldGroups = commentFieldGroups(meta, subject.type, typeMeta);

  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="nowrap">
        <Title order={2}>Comments</Title>
        <CloseButton aria-label="Close the comments panel" onClick={onClose} />
      </Group>

      <Stack gap={6} role="group" aria-label="Comment filters">
        <SegmentedControl
          size="xs"
          aria-label="Status"
          data={[
            { value: 'open', label: 'Open' },
            { value: 'resolved', label: 'Resolved' },
            { value: 'all', label: 'All' },
          ]}
          value={status}
          onChange={(value) => {
            setStatus(pick(STATUS_FILTERS, value) ?? 'open');
          }}
        />
        <Select
          size="xs"
          label="Field"
          placeholder="All fields"
          clearable
          searchable
          data={[{ group: 'Record', items: [{ value: ENTITY_LEVEL, label: 'Entity-level only' }] }, ...fieldGroups]}
          value={fieldFilter}
          onChange={setFieldFilter}
          comboboxProps={{ withinPortal: true }}
        />
        <Switch
          size="xs"
          label="Show deleted"
          checked={showDeleted}
          onChange={(event) => {
            setShowDeleted(event.currentTarget.checked);
          }}
        />
      </Stack>

      <CommentComposer
        subjectId={subject.id}
        maxChars={meta.limits.max_comment_chars}
        label="New comment"
        fieldOptions={fieldGroups}
        field={composerField}
        onFieldChange={setComposerField}
        focusKey={focus?.key}
      />

      {threadId !== null && loaded && !linkedShown && (
        <Alert color="yellow" variant="light">
          <Group justify="space-between" gap="xs">
            <Text size="sm">The linked thread is not shown with these filters (it may be deleted).</Text>
            <Button
              size="compact-xs"
              variant="light"
              onClick={() => {
                setStatus('all');
                setFieldFilter(null);
                setShowDeleted(true);
              }}
            >
              Show all
            </Button>
          </Group>
        </Alert>
      )}

      {threads.isPending && <Loader size="sm" />}
      {threads.isError && (
        <ErrorAlert title="Could not load the comments" error={threads.error} onRetry={() => void threads.refetch()} />
      )}
      {loaded?.length === 0 && (
        <Text size="sm" c="dimmed">
          No comments with these filters.
        </Text>
      )}
      {loaded?.map((thread) => (
        <CommentThreadView
          key={thread.root.id}
          thread={thread}
          fieldLabel={fieldLabelOf(typeMeta, thread.root.field)}
          highlighted={thread.root.id === threadId}
          maxChars={meta.limits.max_comment_chars}
          maxNoteChars={meta.limits.max_note_chars}
        />
      ))}
    </Stack>
  );
}
