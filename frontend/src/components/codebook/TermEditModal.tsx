// Edit a vocabulary term (docs/UI.md §5): a generic PATCH of
// `vocabulary_term` with the registry's editable fields; vocabulary and code
// are read-only. The form starts from the term's values and sends only the
// fields that differ from them.
import { Alert, Button, Group, Loader, Modal, Stack, Text, TextInput, Textarea } from '@mantine/core';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import { validationErrors } from '../../api/client';
import { useEntity, usePatchEntity } from '../../api/queries';
import type { FieldSpec, Item, JsonObject, JsonValue, Vocabulary } from '../../api/types';
import { fieldValueError, isMissingRequired } from '../../lib/field-validation';
import { asString } from '../../lib/format';
import { errorMessage, ErrorAlert, notifySuccess } from '../feedback';
import { FieldLabel } from '../fields/FieldInput';
import { TermAttributes } from './TermAttributes';
import { ModificationSwitch, TermFieldInputs } from './TermFieldInputs';
import {
  attributesOf,
  changedValues,
  COUNTS_AS_MODIFICATION,
  editableTermFields,
  identityFields,
  isFixedTerm,
  MODIFICATION_VOCABULARY,
  omitKey,
  pickValues,
  splitValidationErrors,
  withAttribute,
} from './term-form';

interface TermFormContext {
  vocabulary: Vocabulary;
  /** Registry fields of vocabulary terms. */
  fields: readonly FieldSpec[];
  maxNoteChars: number;
}

interface TermEditModalProps extends TermFormContext {
  termId: string | null;
  onClose: () => void;
}

export function TermEditModal({ termId, onClose, ...context }: TermEditModalProps) {
  const code = context.vocabulary.terms.find((term) => term.id === termId)?.code ?? '';
  return (
    <Modal opened={termId !== null} onClose={onClose} size="lg" title={`Edit term ${context.vocabulary.name}:${code}`}>
      {termId !== null && <TermEditLoader termId={termId} {...context} onDone={onClose} />}
    </Modal>
  );
}

/** Loads the term with all its registry fields. */
function TermEditLoader({ termId, onDone, ...context }: TermFormContext & { termId: string; onDone: () => void }) {
  const term = useEntity('vocabulary_term', termId);
  if (term.isError) return <ErrorAlert title="Could not load the term" error={term.error} onRetry={() => void term.refetch()} />;
  if (!term.data) return <Loader size="sm" aria-label="Loading the term" />;
  return <TermEditForm item={term.data.item} {...context} onDone={onDone} />;
}

interface TermEditFormProps extends TermFormContext {
  item: Item;
  onDone: () => void;
}

function TermEditForm({ item, fields, maxNoteChars, vocabulary, onDone }: TermEditFormProps) {
  const patch = usePatchEntity('vocabulary_term');
  const editable = editableTermFields(fields);
  // The term's values when the form opened; a save sends what differs from them.
  const [initial] = useState(() => pickValues(item.fields, [...editable.map((field) => field.name), 'attributes']));
  const [values, setValues] = useState<JsonObject>(initial);
  const [note, setNote] = useState('');
  const [serverErrors, setServerErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const changes = changedValues(initial, values);
  const hasChanges = Object.keys(changes).length > 0;
  const fixed = isFixedTerm(vocabulary, initial.attributes);
  const code = asString(item.fields.code);
  const withModificationSwitch = vocabulary.name === MODIFICATION_VOCABULARY;
  const initialCounts = attributesOf(initial.attributes)[COUNTS_AS_MODIFICATION] === true;
  const counts = attributesOf(values.attributes)[COUNTS_AS_MODIFICATION] === true;

  const clientErrors: Record<string, string> = {};
  for (const field of editable) {
    const value = values[field.name] ?? null;
    const error = isMissingRequired(field, value) ? 'Required.' : fieldValueError(field, value);
    if (error) clientErrors[field.name] = error;
  }
  const invalid = Object.keys(clientErrors).length > 0;

  const setValue = (name: string, value: JsonValue) => {
    setValues((previous) => {
      const next = { ...previous, [name]: value };
      // A replacement is allowed only for inactive terms.
      if (name === 'active' && value === true) next.replaced_by = null;
      return next;
    });
    setServerErrors((previous) => omitKey(previous, name));
  };

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (invalid || !hasChanges) return;
    setFormError(null);
    try {
      const result = await patch.mutateAsync({ id: item.id, changes, note: note.trim() || null });
      const summary = result.changed ? `Saved ${item.label}.` : `Nothing changed in ${item.label}.`;
      notifySuccess([summary, ...result.warnings.map((warning) => warning.message)].join(' '));
      onDone();
    } catch (error) {
      const details = validationErrors(error);
      if (details) {
        const { byField, other } = splitValidationErrors(details, editable.map((field) => field.name));
        setServerErrors(byField);
        setFormError(other.length > 0 ? other.join('\n') : null);
      } else setFormError(errorMessage(error));
    }
  };

  const otherAttributes = Object.fromEntries(
    Object.entries(attributesOf(initial.attributes)).filter(([key]) => !withModificationSwitch || key !== COUNTS_AS_MODIFICATION),
  );
  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        <Group grow gap="sm">
          {identityFields(fields).map((field) => (
            <TextInput
              key={field.name}
              label={<FieldLabel field={field} />}
              value={asString(item.fields[field.name] ?? null) ?? ''}
              readOnly
              variant="filled"
              description="Cannot be changed"
            />
          ))}
        </Group>
        <TermFieldInputs
          fields={editable}
          values={values}
          onChange={setValue}
          errors={{ ...(submitted ? clientErrors : {}), ...serverErrors }}
          vocabulary={vocabulary}
          ownCode={code}
          fixed={fixed}
        />
        {withModificationSwitch && (
          <ModificationSwitch
            checked={counts}
            changed={counts !== initialCounts}
            onChange={(checked) => {
              setValue(
                'attributes',
                checked === initialCounts ? initial.attributes ?? null : withAttribute(values.attributes, COUNTS_AS_MODIFICATION, checked),
              );
            }}
          />
        )}
        {Object.keys(otherAttributes).length > 0 && (
          <Group gap={6}>
            <Text size="sm" c="dimmed">
              Other attributes (read-only):
            </Text>
            <TermAttributes attributes={otherAttributes} />
          </Group>
        )}
        <Textarea
          label="Change note (optional)"
          autosize
          minRows={2}
          maxLength={maxNoteChars}
          value={note}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
        />
        {formError && (
          <Alert color="red" variant="light" title="The term was not saved" style={{ whiteSpace: 'pre-line' }}>
            {formError}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={patch.isPending} disabled={!hasChanges || (submitted && invalid)}>
            Save
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
