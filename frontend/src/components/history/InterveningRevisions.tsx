// The revisions written since the version a user acted on (`intervening` of a
// 409 conflict): shown when an action is confirmed again (docs/UI.md §1.3).
import { Group, List, Text } from '@mantine/core';

import type { RevisionSummary } from '../../api/types';
import { Timestamp } from '../Timestamp';
import { ActionBadge, ChangedFieldChips } from './RevisionBadges';

interface InterveningRevisionsProps {
  revisions: readonly RevisionSummary[];
  fieldLabels?: Readonly<Record<string, string>>;
}

export function InterveningRevisions({ revisions, fieldLabels }: InterveningRevisionsProps) {
  return (
    <List size="sm" spacing={6} listStyleType="none" p={0}>
      {revisions.map((revision) => (
        <List.Item key={revision.id}>
          <Group gap={6} wrap="wrap">
            <Text span fw={600}>
              v{revision.version}
            </Text>
            <Timestamp value={revision.at} />
            <bdi>{revision.author}</bdi>
            <ActionBadge action={revision.action} />
            <ChangedFieldChips fields={revision.changed_fields} labels={fieldLabels} />
          </Group>
          {revision.note && (
            <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
              {revision.note}
            </Text>
          )}
        </List.Item>
      ))}
    </List>
  );
}
