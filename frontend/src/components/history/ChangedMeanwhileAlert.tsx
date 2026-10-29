// After a 409 conflict on an action that is confirmed again (delete, undelete,
// restore, comment actions, the codebook dialogs; docs/UI.md §1.3): the
// revisions written since the user opened the dialog, with author, time, note
// and changed fields, then the question the confirm button answers.
import { Alert, Text } from '@mantine/core';
import type { ReactNode } from 'react';

import type { RevisionSummary } from '../../api/types';
import { InterveningRevisions } from './InterveningRevisions';

interface ChangedMeanwhileAlertProps {
  /** The intervening revisions of the conflict payload. */
  revisions: readonly RevisionSummary[];
  /** The question the confirm button answers, e.g. "Delete it anyway?". */
  question: string;
  fieldLabels?: Readonly<Record<string, string>>;
  /** Extra details, e.g. the fields both people changed. */
  children?: ReactNode;
}

export function ChangedMeanwhileAlert({ revisions, question, fieldLabels, children }: ChangedMeanwhileAlertProps) {
  return (
    <Alert color="yellow" variant="light" title="Changed since you opened this dialog">
      <InterveningRevisions revisions={revisions} fieldLabels={fieldLabels} />
      {children}
      <Text size="sm" mt="xs" fw={500}>
        {question}
      </Text>
    </Alert>
  );
}
