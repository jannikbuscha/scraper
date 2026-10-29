// Bulk edit of the selected rows (docs/UI.md §3): a bulk_editable field, the
// operation (set, or add/remove for lists), the value and a note. Changing
// the scope asks for a scope note; setting verified or disputed asks for a
// note. Row versions are captured when the dialog opens; the result is shown
// per row. "Mark verified" opens it preset to verification_status = verified.
import { Alert, Button, Group, Modal, SegmentedControl, Select, Stack, Switch, Text, Textarea } from '@mantine/core';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import { useBulkEdit } from '../../api/queries';
import type { BulkResult, FieldSpec, JsonValue } from '../../api/types';
import {
  bulkRequest,
  conflictRetryTargets,
  countBulkResults,
  mergeBulkResults,
  type BulkEdit,
  type BulkOp,
  type BulkTarget,
} from '../../lib/bulk';
import { asString, asStringArray, isEmptyValue, pick, pluralize } from '../../lib/format';
import { requiresScopeNote, requiresVerificationNote } from '../../lib/write-rules';
import { errorMessage, notifySuccess } from '../feedback';
import { ValueDisplay } from '../fields/FieldValue';
import { VocabMultiSelect, VocabSelect } from '../fields/inputs/VocabSelect';
import { BulkResultSummary } from './BulkResultSummary';
import { useTableContext } from './TableContext';

export interface BulkEditRequest {
  /** The selected rows with the versions captured when the dialog opened. */
  targets: BulkTarget[];
  /** "Mark verified": a fixed field and value. */
  preset?: { field: string; value: JsonValue } | undefined;
}

interface BulkEditModalProps {
  request: BulkEditRequest | null;
  onClose: () => void;
}

export function BulkEditModal({ request, onClose }: BulkEditModalProps) {
  const { typeMeta } = useTableContext();
  const rows = request ? pluralize(request.targets.length, typeMeta.label.toLowerCase(), typeMeta.label_plural.toLowerCase()) : '';
  const title = request?.preset ? `Mark verified · ${rows}` : `Bulk edit · ${rows}`;
  return (
    <Modal opened={request !== null} onClose={onClose} title={title} size="lg">
      {request && <BulkEditForm request={request} onDone={onClose} />}
    </Modal>
  );
}

const LIST_OPS: readonly BulkOp[] = ['set', 'add', 'remove'];
const OP_LABELS: Record<BulkOp, string> = { set: 'Replace with', add: 'Add', remove: 'Remove' };

const initialValue = (field: FieldSpec | undefined): JsonValue =>
  field?.type === 'bool' ? false : field?.type === 'vocab_list' ? [] : null;

interface ValueInputProps {
  field: FieldSpec;
  op: BulkOp;
  value: JsonValue;
  onChange: (value: JsonValue) => void;
  error: ReactNode;
}

/** The value input of a bulk_editable field (vocab, vocab_list or bool). */
function ValueInput({ field, op, value, onChange, error }: ValueInputProps) {
  if (field.type === 'bool') {
    return (
      <Switch
        label={`${field.label}: ${value === true ? 'yes' : 'no'}`}
        checked={value === true}
        onChange={(event) => {
          onChange(event.currentTarget.checked);
        }}
      />
    );
  }
  if (field.type === 'vocab_list') {
    return (
      <VocabMultiSelect
        label={op === 'set' ? 'New values (the first is the main value)' : op === 'add' ? 'Values to add' : 'Values to remove'}
        description={op === 'add' ? 'Missing values are appended in this order.' : undefined}
        vocabulary={field.vocabulary}
        value={asStringArray(value)}
        onChange={onChange}
        markMain={op === 'set'}
        error={error}
      />
    );
  }
  return (
    <VocabSelect
      label="New value"
      description={field.required ? undefined : 'Leave empty to clear the field.'}
      vocabulary={field.vocabulary}
      value={asString(value)}
      onChange={onChange}
      required={field.required}
      error={error}
    />
  );
}

function BulkEditForm({ request, onDone }: { request: BulkEditRequest; onDone: () => void }) {
  const { type, meta, typeMeta } = useTableContext();
  const bulk = useBulkEdit(type);
  const { targets, preset } = request;
  const fields = typeMeta.fields.filter((field) => field.bulk_editable);
  const [fieldName, setFieldName] = useState<string | null>(preset?.field ?? null);
  const field = typeMeta.fields.find((candidate) => candidate.name === fieldName);
  const [op, setOp] = useState<BulkOp>('set');
  const [value, setValue] = useState<JsonValue>(preset ? preset.value : null);
  const [scopeNote, setScopeNote] = useState('');
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [requestError, setRequestError] = useState<unknown>(null);
  const [sent, setSent] = useState<{ edit: BulkEdit; note: string | null } | null>(null);
  const [results, setResults] = useState<Map<string, BulkResult> | null>(null);

  const change = field ? { [field.name]: value } : {};
  const scopeNoteNeeded = requiresScopeNote(change);
  const noteNeeded = requiresVerificationNote(change);
  const tooMany = targets.length > meta.limits.max_bulk_items;
  const errors = {
    field: field ? null : 'Choose a field.',
    value:
      field && op !== 'set' && isEmptyValue(value)
        ? 'Choose at least one value.'
        : field?.required && isEmptyValue(value)
          ? 'This field cannot be empty.'
          : null,
    scopeNote: scopeNoteNeeded && scopeNote.trim() === '' ? 'Changing the scope needs a scope note (the reason).' : null,
    note: noteNeeded && note.trim() === '' ? 'Setting verified or disputed needs a note.' : null,
  };
  const invalid = Object.values(errors).some((error) => error !== null) || tooMany;

  const run = async (rows: readonly BulkTarget[], edit: BulkEdit, editNote: string | null) => {
    setRequestError(null);
    try {
      const response = await bulk.mutateAsync(bulkRequest(rows, edit, editNote));
      const merged = mergeBulkResults(results ?? new Map<string, BulkResult>(), response.results);
      setResults(merged);
      const counts = countBulkResults(merged);
      if (counts.conflict + counts.entity_deleted + counts.error === 0) {
        notifySuccess(`${pluralize(counts.updated, 'row')} updated, ${counts.unchanged} unchanged.`);
      }
    } catch (error) {
      setRequestError(error);
    }
  };

  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!field || invalid) return;
    const edit: BulkEdit = scopeNoteNeeded
      ? { field: field.name, op, value, alongside: { scope_note: scopeNote.trim() } }
      : { field: field.name, op, value };
    const editNote = note.trim() || null;
    setSent({ edit, note: editNote });
    void run(targets, edit, editNote);
  };

  const shown = (error: string | null) => (submitted ? error : null);
  const requestErrorAlert = requestError !== null && (
    <Alert color="red" variant="light" title="The bulk edit was refused" style={{ whiteSpace: 'pre-line' }}>
      {errorMessage(requestError)}
    </Alert>
  );

  if (results && sent) {
    return (
      <Stack gap="sm">
        {requestErrorAlert}
        <BulkResultSummary
          targets={targets}
          results={results}
          fields={typeMeta.fields}
          retrying={bulk.isPending}
          onRetry={() => void run(conflictRetryTargets(targets, results), sent.edit, sent.note)}
          onClose={onDone}
        />
      </Stack>
    );
  }

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          Applies to {pluralize(targets.length, 'selected row')}, at the versions shown when this dialog opened. Rows
          changed by someone else in the meantime are reported, not overwritten.
        </Text>
        {tooMany && (
          <Alert color="red" variant="light">
            At most {meta.limits.max_bulk_items} rows can be edited at once.
          </Alert>
        )}
        {preset && field ? (
          <Group gap={6}>
            <Text size="sm">
              Set <strong>{field.label}</strong> to
            </Text>
            <ValueDisplay field={field} value={preset.value} />
          </Group>
        ) : (
          <>
            <Select
              label="Field"
              data={fields.map((candidate) => ({ value: candidate.name, label: candidate.label }))}
              value={fieldName}
              onChange={(name) => {
                setFieldName(name);
                setOp('set');
                setValue(initialValue(typeMeta.fields.find((candidate) => candidate.name === name)));
              }}
              searchable
              required
              error={shown(errors.field)}
              comboboxProps={{ withinPortal: true }}
              data-autofocus
            />
            {field?.type === 'vocab_list' && (
              <SegmentedControl
                aria-label="Operation"
                data={LIST_OPS.map((candidate) => ({ value: candidate, label: OP_LABELS[candidate] }))}
                value={op}
                onChange={(next) => {
                  setOp(pick(LIST_OPS, next) ?? 'set');
                }}
              />
            )}
            {field && (
              <ValueInput field={field} op={op} value={value} onChange={setValue} error={shown(errors.value)} />
            )}
          </>
        )}
        {scopeNoteNeeded && (
          <Textarea
            label="Scope note"
            description="Why these rows are in or out of the paper's scope; replaces each row's scope note."
            required
            autosize
            minRows={2}
            value={scopeNote}
            error={shown(errors.scopeNote)}
            onChange={(event) => {
              setScopeNote(event.currentTarget.value);
            }}
          />
        )}
        <Textarea
          label={noteNeeded ? 'Change note' : 'Change note (optional)'}
          description={noteNeeded ? 'Required: what was checked, or why it is disputed.' : undefined}
          required={noteNeeded}
          autosize
          minRows={2}
          maxLength={meta.limits.max_note_chars}
          value={note}
          error={shown(errors.note)}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
        />
        {requestErrorAlert}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" loading={bulk.isPending} disabled={tooMany || (submitted && invalid)}>
            {preset ? 'Mark verified' : 'Apply'}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
