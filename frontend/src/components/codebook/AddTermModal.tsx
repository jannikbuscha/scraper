// Add a term to a vocabulary (docs/UI.md §5; not offered for fixed
// vocabularies): the vocabulary is fixed by the page, the code is entered
// once (`^[a-z0-9_]+$`, never renamed), the other fields come from the
// registry's create fields with their defaults.
import { Alert, Button, Group, Modal, Stack, TextInput, Textarea } from '@mantine/core';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import { uniqueViolation, validationErrors } from '../../api/client';
import { useCreateEntity } from '../../api/queries';
import type { FieldSpec, JsonObject, JsonValue, Vocabulary } from '../../api/types';
import { fieldValueError, isMissingRequired } from '../../lib/field-validation';
import { asString, isEmptyValue } from '../../lib/format';
import { errorMessage, notifySuccess } from '../feedback';
import { FieldInput, FieldLabel } from '../fields/FieldInput';
import { ModificationSwitch, TermFieldInputs } from './TermFieldInputs';
import {
  COUNTS_AS_MODIFICATION,
  createTermFields,
  identityFields,
  MODIFICATION_VOCABULARY,
  omitKey,
  splitValidationErrors,
} from './term-form';

const CODE_PATTERN = /^[a-z0-9_]+$/;
const CODE_HINT = 'Lowercase letters, digits and underscores, e.g. example_code. It cannot be changed later.';
const CODE_ERROR = 'Use only lowercase letters, digits and underscores.';

interface AddTermFormProps {
  vocabulary: Vocabulary;
  /** Registry fields of vocabulary terms. */
  fields: readonly FieldSpec[];
  maxNoteChars: number;
}

interface AddTermModalProps extends AddTermFormProps {
  opened: boolean;
  onClose: () => void;
}

export function AddTermModal({ opened, onClose, ...props }: AddTermModalProps) {
  return (
    <Modal opened={opened} onClose={onClose} size="lg" title={`Add a term to ${props.vocabulary.label}`}>
      {opened && <AddTermForm {...props} onDone={onClose} />}
    </Modal>
  );
}

const emptyValue = (field: FieldSpec): JsonValue => (field.type === 'bool' ? false : field.type.endsWith('_list') ? [] : null);

function AddTermForm({ vocabulary, fields, maxNoteChars, onDone }: AddTermFormProps & { onDone: () => void }) {
  const create = useCreateEntity('vocabulary_term');
  // The vocabulary comes from the page; the other identity fields (the code) are entered.
  const identity = identityFields(fields).filter((field) => field.name !== 'vocabulary');
  const inputs = [...identity, ...createTermFields(fields)];
  const [values, setValues] = useState<JsonObject>(() =>
    Object.fromEntries(inputs.map((field) => [field.name, field.default ?? emptyValue(field)])),
  );
  const [counts, setCounts] = useState(false);
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const withModificationSwitch = vocabulary.name === MODIFICATION_VOCABULARY;

  const clientErrors: Record<string, string> = {};
  for (const field of inputs) {
    const value = values[field.name] ?? null;
    const error = isMissingRequired(field, value) ? 'Required.' : fieldValueError(field, value);
    if (error) clientErrors[field.name] = error;
  }
  const code = asString(values.code ?? null)?.trim() ?? '';
  if (!clientErrors.code && code !== '' && !CODE_PATTERN.test(code)) clientErrors.code = CODE_ERROR;
  const invalid = Object.keys(clientErrors).length > 0;

  const setValue = (name: string, value: JsonValue) => {
    setValues((previous) => ({ ...previous, [name]: value }));
    setServerErrors((previous) => omitKey(previous, name));
  };

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (invalid) return;
    setFormError(null);
    // Empty values are "not provided"; false is a value.
    const data: JsonObject = Object.fromEntries(Object.entries(values).filter(([, value]) => !isEmptyValue(value)));
    data.vocabulary = vocabulary.name;
    if (withModificationSwitch) data.attributes = { [COUNTS_AS_MODIFICATION]: counts };
    try {
      const result = await create.mutateAsync({ data, note: note.trim() || null });
      notifySuccess([`Added ${result.item.label}.`, ...result.warnings.map((warning) => warning.message)].join(' '));
      onDone();
    } catch (error) {
      const details = validationErrors(error);
      const unique = uniqueViolation(error);
      if (details) {
        const { byField, other } = splitValidationErrors(details, inputs.map((field) => field.name));
        setServerErrors(byField);
        setFormError(other.length > 0 ? other.join('\n') : null);
      } else if (unique) {
        setServerErrors({ [unique.field]: `Already used by ${unique.existing.label}.` });
      } else setFormError(errorMessage(error));
    }
  };

  const errors = { ...(submitted ? clientErrors : {}), ...serverErrors };
  const vocabularyField = fields.find((field) => field.name === 'vocabulary');
  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        <TextInput
          label={vocabularyField ? <FieldLabel field={vocabularyField} /> : 'Vocabulary'}
          value={vocabulary.name}
          readOnly
          variant="filled"
        />
        {identity.map((field) => (
          <FieldInput
            key={field.name}
            field={field}
            value={values[field.name] ?? null}
            required
            description={field.name === 'code' ? CODE_HINT : undefined}
            error={errors[field.name]}
            onChange={(value) => {
              setValue(field.name, value);
            }}
          />
        ))}
        <TermFieldInputs
          fields={createTermFields(fields)}
          values={values}
          onChange={setValue}
          errors={errors}
          vocabulary={vocabulary}
          ownCode={null}
          fixed={false}
        />
        {withModificationSwitch && <ModificationSwitch checked={counts} changed={counts} onChange={setCounts} />}
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
          <Alert color="red" variant="light" title="The term was not added" style={{ whiteSpace: 'pre-line' }}>
            {formError}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending} disabled={submitted && invalid}>
            Add term
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
