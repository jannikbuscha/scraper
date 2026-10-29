// Comment composer (docs/UI.md §4.3): a Markdown textarea limited to
// meta.limits.max_comment_chars, with an optional field selector for new
// threads. There is no client-side preview; the server renders body_html.
import { Alert, Button, Group, Select, Stack, Text, Textarea } from '@mantine/core';
import { useEffect, useRef, useState, type SubmitEvent } from 'react';

import { useCreateComment } from '../../api/queries';
import { errorMessage } from '../feedback';
import { WriteButton } from '../WriteButton';
import { ENTITY_LEVEL, type FieldOptionGroup } from './comment-fields';

interface CommentComposerProps {
  subjectId: string;
  maxChars: number;
  /** Label of the textarea, e.g. "New comment" or "Reply". */
  label: string;
  /** A reply to this root; replies have no field selector. */
  parentId?: string | undefined;
  /** Field selector of a new thread. */
  fieldOptions?: FieldOptionGroup[] | undefined;
  field?: string | null | undefined;
  onFieldChange?: ((field: string | null) => void) | undefined;
  /** Focuses the textarea whenever this value changes. */
  focusKey?: number | undefined;
  onCancel?: (() => void) | undefined;
  onPosted?: (() => void) | undefined;
}

export function CommentComposer({
  subjectId,
  maxChars,
  label,
  parentId,
  fieldOptions,
  field = null,
  onFieldChange,
  focusKey,
  onCancel,
  onPosted,
}: CommentComposerProps) {
  const create = useCreateComment();
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (focusKey !== undefined) textarea.current?.focus();
  }, [focusKey]);

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    if (text.trim() === '') return;
    setError(null);
    try {
      await create.mutateAsync(
        parentId === undefined
          ? { subject_id: subjectId, field, parent_id: null, body_md: text }
          : { subject_id: subjectId, parent_id: parentId, body_md: text },
      );
      setText('');
      onPosted?.();
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap={6}>
        {fieldOptions && (
          <Select
            label="About"
            size="xs"
            data={[{ group: 'Record', items: [{ value: ENTITY_LEVEL, label: 'The whole record' }] }, ...fieldOptions]}
            value={field ?? ENTITY_LEVEL}
            allowDeselect={false}
            searchable
            onChange={(value) => {
              onFieldChange?.(value === null || value === ENTITY_LEVEL ? null : value);
            }}
            comboboxProps={{ withinPortal: true }}
          />
        )}
        <Textarea
          ref={textarea}
          label={label}
          description="Markdown; links, lists, emphasis and tables are kept."
          autosize
          minRows={2}
          maxRows={10}
          maxLength={maxChars}
          value={text}
          onChange={(event) => {
            setText(event.currentTarget.value);
          }}
        />
        {error && (
          <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
            {error}
          </Alert>
        )}
        <Group justify="space-between" gap="xs">
          <Text size="xs" c="dimmed">
            {text.length} / {maxChars}
          </Text>
          <Group gap="xs">
            {onCancel && (
              <Button variant="default" onClick={onCancel}>
                Cancel
              </Button>
            )}
            <WriteButton type="submit" loading={create.isPending} disabled={text.trim() === ''}>
              {parentId === undefined ? 'Comment' : 'Reply'}
            </WriteButton>
          </Group>
        </Group>
      </Stack>
    </form>
  );
}
