// Edit mode of the detail page (docs/UI.md §4.1). The form starts from the
// record's fields and keeps its values in component state; the PATCH sends
// only the changed fields.
import { Alert, Button, Group, Modal, Stack, Text } from '@mantine/core';
import { useBlocker, type ShouldBlockFn } from '@tanstack/react-router';
import { useCallback, useRef, useState, type ReactNode } from 'react';

import { referenceDeleted, uniqueViolation, validationErrors } from '../../api/client';
import { usePatchEntity } from '../../api/queries';
import type { EntityTypeMeta, Item, JsonValue, Meta, RecordType } from '../../api/types';
import { DETAIL_PATHS, isRecordPageType, isTableType, RECORD_PATH, type DetailEntityType } from '../../lib/entity';
import { asString, pluralize } from '../../lib/format';
import { requiresScopeNote, requiresVerificationNote } from '../../lib/write-rules';
import { AnchorLink } from '../AnchorLink';
import { errorMessage, notifyError, notifySuccess } from '../feedback';
import { changedValues, editableFields, editErrors, hasEditErrors, startEditSession, type EditSession } from './edit-session';
import { EditFields } from './EditFields';
import { SaveBar } from './SaveBar';

interface EditFormProps {
  type: DetailEntityType;
  item: Item;
  meta: Meta;
  typeMeta: EntityTypeMeta;
  /** Leaves edit mode (removes `edit=1`); the unsaved-changes prompt guards it. */
  onLeave: () => void;
}

/** Server error paths may be prefixed (`changes.name_en`); the last segment is the field. */
const fieldOfPath = (path: string): string => path.split('.').pop() ?? path;

const withoutKey = <T,>(record: Record<string, T>, key: string): Record<string, T> =>
  Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));

/** A link that opens in a new tab, so the form keeps its values. */
function NewTabLink({ type, id, label }: { type: RecordType; id: string; label: string }) {
  if (isRecordPageType(type)) {
    return (
      <AnchorLink to={RECORD_PATH} params={{ id }} target="_blank" rel="noopener noreferrer">
        <bdi>{label}</bdi>
      </AnchorLink>
    );
  }
  if (!isTableType(type)) return <bdi>{label}</bdi>;
  return (
    <AnchorLink to={DETAIL_PATHS[type]} params={{ id }} target="_blank" rel="noopener noreferrer">
      <bdi>{label}</bdi>
    </AnchorLink>
  );
}

export function EditForm({ type, item, meta, typeMeta, onLeave }: EditFormProps) {
  const patch = usePatchEntity(type);
  const [session, setSession] = useState<EditSession>(() => startEditSession(item));
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, ReactNode>>({});
  const [formError, setFormError] = useState<ReactNode>(null);

  const editable = editableFields(typeMeta);
  const editableNames = new Set(editable.map((field) => field.name));
  const changes = changedValues(session, editable);
  const errors = editErrors(session, typeMeta, changes, note);
  const dirty = Object.keys(changes).length > 0;

  // Unsaved changes trigger a prompt when leaving the page or edit mode.
  const allowLeave = useRef(false);
  const shouldBlockFn = useCallback<ShouldBlockFn>(
    ({ current, next }) => !allowLeave.current && (current.pathname !== next.pathname || next.search.edit !== '1'),
    [],
  );
  const blocker = useBlocker({ shouldBlockFn, enableBeforeUnload: dirty, disabled: !dirty, withResolver: true });

  const leave = (force: boolean) => {
    allowLeave.current = force;
    onLeave();
  };

  /** An error about one field: at its input, or above the save bar for fields without one (e.g. system fields). */
  const showAtField = (field: string, message: ReactNode) => {
    const label = typeMeta.fields.find((spec) => spec.name === field)?.label ?? field;
    if (editableNames.has(field)) setServerErrors({ [field]: message });
    else {
      setFormError(
        <>
          {label}: {message}
        </>,
      );
    }
  };

  const showServerError = (error: unknown) => {
    const details = validationErrors(error);
    const unique = uniqueViolation(error);
    const reference = referenceDeleted(error);
    if (details) {
      const byField: Record<string, ReactNode> = {};
      const other: string[] = [];
      for (const [path, messages] of Object.entries(details)) {
        const name = fieldOfPath(path);
        if (editableNames.has(name)) byField[name] = messages.join(' ');
        else other.push(`${path}: ${messages.join(' ')}`);
      }
      setServerErrors(byField);
      setFormError(other.length > 0 ? other.join('\n') : null);
    } else if (unique) {
      showAtField(
        unique.field,
        <>
          Already used by <NewTabLink type={type} id={unique.existing.id} label={unique.existing.label} />
          {unique.existing.deleted && ' (in the trash)'}.
        </>,
      );
    } else if (reference) {
      showAtField(
        reference.field,
        <>
          <NewTabLink type={reference.type} id={reference.id} label={reference.label} /> is deleted. Open it (new tab)
          to undelete it, or choose another.
        </>,
      );
    } else {
      setFormError(errorMessage(error));
      notifyError(error, 'Could not save the changes');
    }
  };

  const save = async () => {
    setSubmitted(true);
    if (hasEditErrors(errors)) return;
    if (!dirty) {
      leave(true);
      return;
    }
    setFormError(null);
    try {
      const result = await patch.mutateAsync({ id: item.id, changes, note: note.trim() || null });
      notifySuccess(
        [
          result.changed ? `Saved as version ${result.item.version}.` : 'Nothing changed on the server.',
          ...result.warnings.map((warning) => warning.message),
        ].join(' '),
      );
      leave(true);
    } catch (error) {
      showServerError(error);
    }
  };

  const setValue = (field: string, value: JsonValue) => {
    setSession((previous) => ({ ...previous, values: { ...previous.values, [field]: value } }));
    setServerErrors((previous) => withoutKey(previous, field));
  };

  const fieldErrors: Record<string, ReactNode> = { ...(submitted ? errors.fields : {}), ...serverErrors };
  const scopeNoteRequired = requiresScopeNote(changes);

  return (
    <Stack gap="md">
      <EditFields
        type={type}
        item={item}
        meta={meta}
        typeMeta={typeMeta}
        editable={editableNames}
        values={session.values}
        errors={fieldErrors}
        alsoRequired={scopeNoteRequired ? new Set(['scope_note']) : new Set()}
        onChange={setValue}
      />

      {formError !== null && (
        <Alert color="red" variant="light" title="Not saved" style={{ whiteSpace: 'pre-line' }}>
          {formError}
        </Alert>
      )}

      <SaveBar
        changedCount={Object.keys(changes).length}
        note={note}
        onNoteChange={setNote}
        noteRequired={requiresVerificationNote(changes)}
        noteError={submitted ? errors.note : null}
        scopeNote={
          scopeNoteRequired
            ? {
                value: asString(session.values.scope_note ?? null) ?? '',
                onChange: (value) => {
                  setValue('scope_note', value === '' ? null : value);
                },
                error: submitted ? errors.scopeNote : null,
              }
            : null
        }
        maxNoteChars={meta.limits.max_note_chars}
        saving={patch.isPending}
        onSave={() => void save()}
        onCancel={() => {
          leave(false);
        }}
      />

      <Modal opened={blocker.status === 'blocked'} onClose={() => blocker.reset?.()} title="Discard unsaved changes?">
        <Stack gap="sm">
          <Text size="sm">
            {pluralize(Object.keys(changes).length, 'changed field')} {Object.keys(changes).length === 1 ? 'is' : 'are'}{' '}
            not saved yet.
          </Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={() => blocker.reset?.()}>
              Keep editing
            </Button>
            <Button color="red" onClick={() => blocker.proceed?.()}>
              Discard changes
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
