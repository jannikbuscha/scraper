// "Save current view…": stores the canonical query string (docs/UI.md §1.2).
import { Alert, Button, Code, Group, Modal, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { useState, type SubmitEvent } from 'react';

import { validationErrors } from '../../api/client';
import { useCreateEntity } from '../../api/queries';
import type { TableEntityType } from '../../api/types';
import { notifyError, notifySuccess } from '../feedback';

/** `key=value` pairs, decoded, one per line. */
const readableQuery = (query: string): string =>
  [...new URLSearchParams(query)].map(([key, value]) => `${key}=${value}`).join('\n');

interface SaveViewModalProps {
  opened: boolean;
  onClose: () => void;
  type: TableEntityType;
  /** Canonical query string without `?` (and without `page`). */
  query: string;
}

export function SaveViewModal({ opened, onClose, type, query }: SaveViewModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} title="Save current view">
      {opened && <SaveViewForm type={type} query={query} onDone={onClose} />}
    </Modal>
  );
}

function SaveViewForm({ type, query, onDone }: { type: TableEntityType; query: string; onDone: () => void }) {
  const create = useCreateEntity('saved_view');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  // A saved view needs a query (docs/DATA_MODEL.md §3.5); the default view is always available.
  const isDefaultView = query === '';

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    if (isDefaultView) return;
    if (name.trim() === '') {
      setErrors({ name: 'Enter a name.' });
      return;
    }
    try {
      await create.mutateAsync({
        data: { name: name.trim(), entity_type: type, query, description: description.trim() || null },
      });
      notifySuccess(`Saved the view “${name.trim()}”.`);
      onDone();
    } catch (error) {
      const details = validationErrors(error);
      if (details) {
        setErrors(
          Object.fromEntries(Object.entries(details).map(([path, messages]) => [path.split('.').pop() ?? path, messages.join(' ')])),
        );
      }
      notifyError(error, 'Could not save the view');
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        <TextInput
          label="Name"
          required
          data-autofocus
          value={name}
          maxLength={500}
          error={errors.name}
          onChange={(event) => {
            setName(event.currentTarget.value);
          }}
        />
        <Textarea
          label="Description"
          autosize
          minRows={2}
          value={description}
          error={errors.description}
          onChange={(event) => {
            setDescription(event.currentTarget.value);
          }}
        />
        <Stack gap={2}>
          <Text size="xs" c="dimmed">
            Saved query (filters, search, sort, page size, columns):
          </Text>
          <Code block>{isDefaultView ? '(default view)' : readableQuery(query)}</Code>
        </Stack>
        {isDefaultView && (
          <Alert color="gray" variant="light">
            This is the default view, which is always available. Set a filter, search, sort, page size or columns
            first, then save the view.
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending} disabled={isDefaultView}>
            Save view
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
