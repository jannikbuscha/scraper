// Related records per type (docs/UI.md §4.1): read-only lists with empty
// states; projects offer "+ Add service" and "+ Add event", services
// "+ Add event". Columns are layout preferences over registry fields.
import { Group, Stack, Text, Title } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useState } from 'react';

import type { EntityType, Item, Meta, RefLabel, TableEntityType } from '../../api/types';
import { asString } from '../../lib/format';
import { EntityLink } from '../EntityLink';
import { CreateEntityModal } from '../table/CreateEntityModal';
import { WriteButton } from '../WriteButton';
import { DocumentTextPanel } from './DocumentTextPanel';
import { RelatedList, type RelatedListProps } from './RelatedList';

type ListSpec = Omit<RelatedListProps, 'meta' | 'action'> & { key: string; add?: AddSpec };

/** "+ Add …": a create dialog with the reference to this record pre-filled. */
interface AddSpec {
  type: 'service' | 'event';
  field: string;
}

const SERVICE_COLUMNS = ['kind', 'channels', 'status', 'launch'];
const EVENT_COLUMNS = ['event_type', 'date', 'date_basis', 'description_en'];
const DOCUMENT_COLUMNS = ['doc_type', 'published', 'publisher'];
const EVIDENCE_COLUMNS = ['target', 'document_id', 'url', 'quote', 'locator', 'retrieved_at'];

function listsFor(type: TableEntityType, id: string, meta: Meta): ListSpec[] {
  const plural = (listed: EntityType, fallback: string) => meta.entity_types[listed]?.label_plural ?? fallback;
  const events: ListSpec = {
    key: 'events',
    title: plural('event', 'Events'),
    type: 'event',
    query: { 'f.subject_id': `in:${id}`, sort: 'date' },
    columns: EVENT_COLUMNS,
    emptyText: 'No events recorded yet.',
    add: { type: 'event', field: 'subject_id' },
  };
  const documents: ListSpec = {
    key: 'documents',
    title: `Linked ${plural('document', 'Documents').toLowerCase()}`,
    type: 'document',
    query: { 'f.links': `in:${id}` },
    columns: DOCUMENT_COLUMNS,
    emptyText: 'No linked documents yet. Documents arrive with the collectors in Phase 2.',
  };
  const participations = (field: 'subject_id' | 'organization_id', columns: string[]): ListSpec => ({
    key: 'participations',
    title: plural('participation', 'Participations'),
    type: 'participation',
    query: { [`f.${field}`]: `in:${id}` },
    columns,
    emptyText: 'No participations recorded yet.',
  });
  const relations: ListSpec = {
    key: 'relations',
    title: plural('relation', 'Relations'),
    type: 'relation',
    query: { 'f.endpoint': `in:${id}` },
    columns: ['from_id', 'relation_type', 'to_id', 'description'],
    emptyText: 'No relations recorded yet.',
  };
  const indicators: ListSpec = {
    key: 'indicators',
    title: plural('indicator', 'Indicators'),
    type: 'indicator',
    query: { 'f.subject_id': `in:${id}` },
    columns: ['metric', 'value', 'unit', 'as_of'],
    emptyText: 'No indicators recorded yet.',
  };
  const evidence: ListSpec = {
    key: 'evidence',
    title: plural('evidence', 'Evidence'),
    type: 'evidence',
    query: { 'f.subject_id': `in:${id}` },
    columns: EVIDENCE_COLUMNS,
    emptyText: 'No evidence recorded yet. Evidence for a field is added from its verification menu.',
  };
  const subjectParticipations = participations('subject_id', ['organization_id', 'role', 'start', 'end']);

  switch (type) {
    case 'project':
      return [
        {
          key: 'services',
          title: plural('service', 'Services'),
          type: 'service',
          query: { 'f.project_id': `in:${id}` },
          columns: SERVICE_COLUMNS,
          emptyText: 'No services recorded yet.',
          add: { type: 'service', field: 'project_id' },
        },
        events,
        documents,
        subjectParticipations,
        relations,
        indicators,
        evidence,
      ];
    case 'service':
      return [
        {
          key: 'children',
          title: `Child ${plural('service', 'Services').toLowerCase()}`,
          type: 'service',
          query: { 'f.parent_service_id': `in:${id}` },
          columns: SERVICE_COLUMNS,
          emptyText: 'No child services.',
        },
        events,
        documents,
        subjectParticipations,
        relations,
        indicators,
        evidence,
      ];
    case 'event':
      return [evidence];
    case 'document':
      return [
        {
          ...evidence,
          title: `${plural('evidence', 'Evidence')} citing this document`,
          query: { 'f.document_id': `in:${id}` },
          columns: ['subject_id', 'target', 'quote', 'locator'],
          emptyText: 'No evidence cites this document yet.',
        },
      ];
    case 'organization':
      return [participations('organization_id', ['subject_id', 'role', 'start', 'end'])];
  }
}

/** Links to the records this one belongs to: the project and parent of a service, the subject of an event. */
function ParentLinks({ type, item, meta }: { type: TableEntityType; item: Item; meta: Meta }) {
  const names = type === 'service' ? ['project_id', 'parent_service_id'] : type === 'event' ? ['subject_id'] : [];
  const fields = meta.entity_types[type]?.fields ?? [];
  const links = names.flatMap((name) => {
    const id = asString(item.fields[name]);
    const label = fields.find((field) => field.name === name)?.label ?? name;
    return id ? [{ name, id, label, ref: item.refs[name] }] : [];
  });
  if (links.length === 0) return null;
  return (
    <Group gap="lg">
      {links.map(({ name, id, label, ref }) => (
        <Text key={name} size="sm">
          {label}: <EntityLink id={id} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />
        </Text>
      ))}
    </Group>
  );
}

export function RelatedPanels({ type, item, meta }: { type: TableEntityType; item: Item; meta: Meta }) {
  const [adding, setAdding] = useState<AddSpec | null>(null);
  const deleted = item.deleted_at !== null;
  const selfRef: RefLabel = { id: item.id, type, label: item.label, deleted };

  return (
    <Stack gap="md" component="section" aria-label="Related records">
      <Title order={2}>Related records</Title>
      <ParentLinks type={type} item={item} meta={meta} />
      {type === 'document' && <DocumentTextPanel item={item} />}
      {listsFor(type, item.id, meta).map(({ key, add, ...list }) => (
        <RelatedList
          key={key}
          {...list}
          meta={meta}
          action={
            add && (
              <WriteButton
                variant="subtle"
                leftSection={<IconPlus size={14} />}
                // A deleted record cannot be referenced (409 reference_deleted).
                disabled={deleted}
                onClick={() => {
                  setAdding(add);
                }}
              >
                Add {meta.entity_types[add.type]?.label.toLowerCase() ?? add.type}
              </WriteButton>
            )
          }
        />
      ))}
      {adding && (
        <CreateEntityModal
          type={adding.type}
          opened
          onClose={() => {
            setAdding(null);
          }}
          initialValues={{ [adding.field]: item.id }}
          initialRefs={{ [adding.field]: selfRef }}
          // Stay on this page; the new row appears in the list above.
          onCreated={() => undefined}
        />
      )}
    </Stack>
  );
}
