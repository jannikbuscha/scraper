// Deactivate a vocabulary term (docs/UI.md §5): codes are never deleted
// (docs/DATA_MODEL.md §7); an inactive code stays in stored values but can no
// longer be chosen, optionally pointing to its replacement.
import { Alert, Button, Group, Modal, Select, Stack, Text, Textarea } from '@mantine/core';
import { useState, type SubmitEvent } from 'react';

import { usePatchEntity } from '../../api/queries';
import type { Vocabulary, VocabTerm } from '../../api/types';
import { pluralize } from '../../lib/format';
import { errorMessage, notifySuccess } from '../feedback';
import { replacementCodes } from './term-form';

interface DeactivateTermModalProps {
  term: VocabTerm | null;
  vocabulary: Vocabulary;
  maxNoteChars: number;
  onClose: () => void;
}

export function DeactivateTermModal({ term, vocabulary, maxNoteChars, onClose }: DeactivateTermModalProps) {
  return (
    <Modal opened={term !== null} onClose={onClose} title={term ? `Deactivate ${vocabulary.name}:${term.code}` : ''}>
      {term && <DeactivateForm term={term} vocabulary={vocabulary} maxNoteChars={maxNoteChars} onDone={onClose} />}
    </Modal>
  );
}

interface DeactivateFormProps {
  term: VocabTerm;
  vocabulary: Vocabulary;
  maxNoteChars: number;
  onDone: () => void;
}

function DeactivateForm({ term, vocabulary, maxNoteChars, onDone }: DeactivateFormProps) {
  const patch = usePatchEntity('vocabulary_term');
  const [replacedBy, setReplacedBy] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await patch.mutateAsync({
        id: term.id,
        changes: replacedBy === null ? { active: false } : { active: false, replaced_by: replacedBy },
        note: note.trim() || null,
      });
      notifySuccess(`Deactivated ${vocabulary.name}:${term.code}.`);
      onDone();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        <Text size="sm">
          Deactivate <code>{term.code}</code> (<bdi>{term.label_en}</bdi>)? It can no longer be chosen. The{' '}
          {pluralize(term.usage_count, 'record')} that use it keep it; codes are never deleted.
        </Text>
        <Select
          label="Replaced by (optional)"
          description="An active code of this vocabulary that takes its place."
          data={replacementCodes(vocabulary, term.code).map((candidate) => ({
            value: candidate.code,
            label: `${candidate.label_en} (${candidate.code})`,
          }))}
          value={replacedBy}
          onChange={setReplacedBy}
          searchable
          clearable
          comboboxProps={{ withinPortal: true }}
        />
        <Textarea
          label="Note (optional)"
          autosize
          minRows={2}
          maxLength={maxNoteChars}
          value={note}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
        />
        {error && (
          <Alert color="red" variant="light" title="The term was not deactivated" style={{ whiteSpace: 'pre-line' }}>
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" color="red" loading={patch.isPending}>
            Deactivate
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
