// The form of a manual document (docs/UI.md §8.6, docs/API.md §7.8): the
// server's suggested values are editable defaults, only what the person
// submits is written. For an upload the source URL is optional and then needs
// "retrieved at"; for a fetched snapshot URL and retrieval time are the
// fetch's own and are not sent.
import { Alert, Button, Group, Stack, Text, Textarea } from '@mantine/core';
import { useState, type ReactNode, type SubmitEvent } from 'react';

import type { ManualDocumentRequest, ManualDocumentResponse, Snapshot, Suggested } from '../../api/acquisition-types';
import { uniqueViolation, validationErrors } from '../../api/client';
import { useCreateManualDocument } from '../../api/documents';
import type { FieldSpec, JsonObject, JsonValue, Meta } from '../../api/types';
import { fieldValueError, isMissingRequired } from '../../lib/field-validation';
import { apiTimestamp, isEmptyValue } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { errorMessage } from '../feedback';
import { FieldInput } from '../fields/FieldInput';

export type DocumentSource = 'upload' | 'fetch';

/** The document fields the form offers, in this order (docs/API.md §7.8). */
const UPLOAD_FIELDS = ['title', 'url', 'retrieved_at', 'doc_type', 'language', 'publisher', 'published', 'published_basis', 'published_text', 'license'];
const FETCH_FIELDS = ['title', 'doc_type', 'language', 'publisher', 'published', 'published_basis', 'published_text', 'license'];

interface ManualDocumentFormProps {
  source: DocumentSource;
  snapshot: Snapshot;
  suggested: Suggested;
  meta: Meta;
  onCreated: (response: ManualDocumentResponse) => void;
  onCancel: () => void;
}

const REQUEST_FIELDS = [
  'title',
  'url',
  'retrieved_at',
  'doc_type',
  'language',
  'publisher',
  'published',
  'published_basis',
  'published_text',
  'license',
] as const;

/** The request: the snapshot and every filled-in field of `names` (empty values are not sent). */
export function manualDocumentRequest(
  snapshotId: string,
  values: JsonObject,
  names: readonly string[],
  note: string,
): ManualDocumentRequest {
  const request: ManualDocumentRequest = { snapshot_id: snapshotId, note: note.trim() || null };
  for (const name of REQUEST_FIELDS) {
    const value = values[name];
    if (names.includes(name) && typeof value === 'string' && value.trim() !== '') request[name] = value.trim();
  }
  return request;
}

export function ManualDocumentForm({ source, snapshot, suggested, meta, onCreated, onCancel }: ManualDocumentFormProps) {
  const create = useCreateManualDocument();
  const typeMeta = meta.entity_types.document;
  const names = source === 'upload' ? UPLOAD_FIELDS : FETCH_FIELDS;
  const fields = names.flatMap((name) => typeMeta?.fields.find((field) => field.name === name) ?? []);
  const [values, setValues] = useState<JsonObject>(() => ({
    title: suggested.title,
    language: suggested.language,
    publisher: suggested.publisher,
    // Proposed whenever a URL is entered (docs/COLLECTORS.md §10.1).
    retrieved_at: source === 'upload' ? apiTimestamp(new Date()) : null,
  }));
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<ReactNode>(null);

  const value = (name: string): JsonValue => values[name] ?? null;
  const errors: Record<string, string> = {};
  for (const field of fields) {
    if (isMissingRequired(field, value(field.name))) errors[field.name] = 'Required.';
    else {
      const error = fieldValueError(field, value(field.name));
      if (error) errors[field.name] = error;
    }
  }
  if (source === 'upload' && !isEmptyValue(value('url')) && isEmptyValue(value('retrieved_at'))) {
    errors.retrieved_at = 'Required with a source URL.';
  }
  if (!isEmptyValue(value('published')) && isEmptyValue(value('published_basis'))) {
    errors.published_basis = 'Required with a publication date.';
  }
  const hasErrors = Object.keys(errors).length > 0;

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (hasErrors) return;
    setFormError(null);
    // An upload without a URL needs no retrieval time.
    const sent = source === 'upload' && isEmptyValue(value('url')) ? { ...values, retrieved_at: null } : values;
    try {
      const response = await create.mutateAsync(manualDocumentRequest(snapshot.id, sent, names, note));
      onCreated(response);
    } catch (error) {
      const details = validationErrors(error);
      const unique = uniqueViolation(error);
      if (details) {
        const byField: Record<string, ReactNode> = {};
        const other: string[] = [];
        for (const [path, messages] of Object.entries(details)) {
          const name = path.split('.').pop() ?? path;
          if (fields.some((field) => field.name === name)) byField[name] = messages.join(' ');
          else other.push(`${path}: ${messages.join(' ')}`);
        }
        setServerErrors(byField);
        if (other.length > 0) setFormError(other.join('\n'));
      } else if (unique) {
        setFormError(
          <>
            A live document already has this URL:{' '}
            <EntityLink id={unique.existing.id} label={unique.existing.label} type="document" deleted={unique.existing.deleted} />.
          </>,
        );
      } else setFormError(errorMessage(error));
    }
  };

  const input = (field: FieldSpec) => (
    <FieldInput
      key={field.name}
      field={field}
      value={value(field.name)}
      required={field.required || (field.name === 'retrieved_at' && !isEmptyValue(value('url'))) || (field.name === 'published_basis' && !isEmptyValue(value('published')))}
      description={field.name === 'url' ? 'The address the file came from, if it has one.' : undefined}
      error={serverErrors[field.name] ?? (submitted ? errors[field.name] : undefined)}
      onChange={(next) => {
        setValues((previous) => ({ ...previous, [field.name]: next }));
        setServerErrors((previous) => ({ ...previous, [field.name]: undefined }));
      }}
    />
  );

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      <Stack gap="sm">
        {suggested.warnings.map((warning) => (
          <Alert key={warning.code} color="yellow" variant="light">
            {warning.message}
          </Alert>
        ))}
        <Text size="xs" c="dimmed">
          Text extraction: {suggested.extraction_method} ({suggested.char_count} characters). The suggested values are
          defaults; change them as needed.
        </Text>
        {fields.map(input)}
        <Textarea
          label="Note (optional)"
          autosize
          minRows={2}
          maxLength={meta.limits.max_note_chars}
          value={note}
          onChange={(event) => {
            setNote(event.currentTarget.value);
          }}
        />
        {formError && (
          <Alert color="red" variant="light" style={{ whiteSpace: 'pre-line' }}>
            {formError}
          </Alert>
        )}
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending} disabled={submitted && hasErrors}>
            Create
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
