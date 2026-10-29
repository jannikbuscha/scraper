// Sticky save bar of the edit form (docs/UI.md §4.1): the change note
// (required where a rule demands it), a new scope note when the paper scope
// changes, Save and Cancel.
import { Button, Group, Paper, Stack, Text, Textarea } from '@mantine/core';

import { pluralize } from '../../lib/format';
import classes from './detail.module.css';

export interface ScopeNoteInput {
  value: string;
  onChange: (value: string) => void;
  error: string | null;
}

interface SaveBarProps {
  changedCount: number;
  note: string;
  onNoteChange: (note: string) => void;
  noteRequired: boolean;
  noteError: string | null;
  /** Shown when `in_paper_scope` changed: the scope note is part of the same change. */
  scopeNote: ScopeNoteInput | null;
  maxNoteChars: number;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}

export function SaveBar({
  changedCount,
  note,
  onNoteChange,
  noteRequired,
  noteError,
  scopeNote,
  maxNoteChars,
  saving,
  onSave,
  onCancel,
}: SaveBarProps) {
  return (
    <Paper className={classes.saveBar} withBorder shadow="sm" p="xs" role="region" aria-label="Save changes">
      <Stack gap="xs">
        {scopeNote && (
          <Textarea
            label="New scope note"
            description="The paper scope changed: give the reason for the new scope decision."
            required
            autosize
            minRows={1}
            maxRows={4}
            value={scopeNote.value}
            error={scopeNote.error}
            onChange={(event) => {
              scopeNote.onChange(event.currentTarget.value);
            }}
          />
        )}
        <Group align="flex-end" gap="sm" wrap="nowrap">
          <Textarea
            style={{ flex: 1 }}
            label={noteRequired ? 'Change note' : 'Change note (optional)'}
            description={noteRequired ? 'Required: what was checked, or why it is disputed.' : undefined}
            required={noteRequired}
            autosize
            minRows={1}
            maxRows={4}
            maxLength={maxNoteChars}
            value={note}
            error={noteError}
            onChange={(event) => {
              onNoteChange(event.currentTarget.value);
            }}
          />
          <Text size="sm" c="dimmed" pb={6} style={{ whiteSpace: 'nowrap' }}>
            {changedCount === 0 ? 'No changes' : `${pluralize(changedCount, 'field')} changed`}
          </Text>
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={onSave} loading={saving}>
            Save
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
