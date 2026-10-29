// Undelete a deleted entity with a note (docs/UI.md §4 and §5), used by the
// trash and the detail page; a cascade deletion can be undone together
// (`cascade`, docs/API.md §3.2), preselected when the deletion is known to be
// a cascade. Uniqueness and deleted references block an undelete and are
// explained with links.
import { Checkbox, Modal } from '@mantine/core';
import { useState } from 'react';

import { referenceDeleted, uniqueViolation } from '../../api/client';
import { useUndeleteEntity } from '../../api/queries';
import type { EntityType, Item, Meta } from '../../api/types';
import { pluralize } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { notifySuccess } from '../feedback';
import type { DeleteInfo } from './delete-info';
import { UndeleteForm } from './UndeleteForm';

export interface EntityUndeleteTarget {
  type: EntityType;
  item: Item;
  /** Undefined while the batch of the deletion is unknown. */
  info: DeleteInfo | undefined;
}

interface UndeleteEntityModalProps {
  target: EntityUndeleteTarget | null;
  meta: Meta;
  onClose: () => void;
}

export function UndeleteEntityModal({ target, meta, onClose }: UndeleteEntityModalProps) {
  return (
    <Modal opened={target !== null} onClose={onClose} title="Undelete record">
      {target && <UndeleteEntityBody target={target} meta={meta} onDone={onClose} />}
    </Modal>
  );
}

/** The cascade option is offered unless the deletion is known to be a single one. */
const offersCascade = (info: DeleteInfo | undefined): boolean => info === undefined || info.others > 0 || !info.exact;

function cascadeLabel(info: DeleteInfo | undefined): string {
  if (info === undefined || info.others === 0) return 'Also undelete any records deleted together with it';
  const others = pluralize(info.others, 'record');
  return `Also undelete the ${info.exact ? others : `${others} or more`} deleted together with it`;
}

function UndeleteEntityBody({ target, meta, onDone }: { target: EntityUndeleteTarget; meta: Meta; onDone: () => void }) {
  const { type, item, info } = target;
  const undelete = useUndeleteEntity(type);
  // Until the user decides, a known cascade is undone as a whole (the info may load after opening).
  const [choice, setChoice] = useState<boolean | null>(null);
  const cascade = choice ?? (info?.others ?? 0) > 0;
  const fieldLabel = (name: string) => meta.entity_types[type]?.fields.find((field) => field.name === name)?.label ?? name;

  const explainError = (error: unknown) => {
    const unique = uniqueViolation(error);
    if (unique) {
      return (
        <>
          “{fieldLabel(unique.field)}” is already used by{' '}
          <EntityLink id={unique.existing.id} label={unique.existing.label} deleted={unique.existing.deleted} />
          {unique.existing.deleted && ' (in the trash)'}. Change one of the two first.
        </>
      );
    }
    const reference = referenceDeleted(error);
    if (reference) {
      return (
        <>
          “{fieldLabel(reference.field)}” refers to{' '}
          <EntityLink id={reference.id} label={reference.label} type={reference.type} deleted />, which is deleted. Undelete
          that record first, or both together if they were deleted together.
        </>
      );
    }
    return null;
  };

  const withCascade = offersCascade(info) && cascade;
  return (
    <UndeleteForm
      label={item.label}
      maxNoteChars={meta.limits.max_note_chars}
      submit={async (note) => {
        await undelete.mutateAsync({ id: item.id, note, cascade: withCascade });
        notifySuccess(
          withCascade
            ? `Undeleted “${item.label}” and the records deleted together with it.`
            : `Undeleted “${item.label}”.`,
        );
        onDone();
      }}
      explainError={explainError}
      onCancel={onDone}
    >
      {offersCascade(info) && (
        <Checkbox
          label={cascadeLabel(info)}
          checked={cascade}
          onChange={(event) => {
            setChoice(event.currentTarget.checked);
          }}
        />
      )}
    </UndeleteForm>
  );
}
