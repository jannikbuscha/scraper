// Header of the detail page (docs/UI.md §4): breadcrumb, label, badges
// (verification status, project cluster, paper scope, deleted, version) and
// the actions Edit, Delete / Undelete, Copy link and the comments toggle.
import { Badge, Breadcrumbs, Button, Group, Stack, Title } from '@mantine/core';
import { IconMessage, IconPencil, IconRestore, IconTrash } from '@tabler/icons-react';

import type { EntityTypeMeta, Item } from '../../api/types';
import { useVocabIndex } from '../../hooks/useVocabIndex';
import { detailHref, isTableType, TABLE_PATHS, type DetailEntityType } from '../../lib/entity';
import { asBoolean, asNumber, asString } from '../../lib/format';
import { termLabel } from '../../lib/vocab';
import { AnchorLink } from '../AnchorLink';
import { isVerificationStatus, VerificationDot } from '../fields/VerificationDot';
import { VocabBadge } from '../fields/VocabBadge';
import { WriteButton } from '../WriteButton';
import { CopyLinkButton } from './CopyLinkButton';

/** The record's paper-scope flag: stored for projects, virtual for the other types. */
function scopeField(typeMeta: EntityTypeMeta) {
  return typeMeta.fields.find(
    (field) => field.type === 'bool' && (field.name === 'in_paper_scope' || field.name.endsWith('_in_paper_scope')),
  );
}

function ScopeBadge({ item, typeMeta }: { item: Item; typeMeta: EntityTypeMeta }) {
  const field = scopeField(typeMeta);
  if (!field) return null;
  const value = asBoolean(item.fields[field.name] ?? item.virtual[field.name]);
  if (value === null) return null;
  return (
    <Badge variant="light" color={value ? 'green' : 'gray'}>
      {field.label}: {value ? 'yes' : 'no'}
    </Badge>
  );
}

interface DetailHeaderProps {
  type: DetailEntityType;
  item: Item;
  typeMeta: EntityTypeMeta;
  editing: boolean;
  commentsOpen: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onUndelete: () => void;
  onToggleComments: () => void;
}

export function DetailHeader({
  type,
  item,
  typeMeta,
  editing,
  commentsOpen,
  onEdit,
  onDelete,
  onUndelete,
  onToggleComments,
}: DetailHeaderProps) {
  const vocab = useVocabIndex();
  const deleted = item.deleted_at !== null;
  const status = asString(item.fields.verification_status);
  // The project's paper cluster (a layout preference; other types have none).
  const clusterField = typeMeta.fields.find((field) => field.name === 'paper_cluster');
  const cluster = clusterField ? asString(item.fields[clusterField.name]) : null;
  const openComments = asNumber(item.virtual.open_comments) ?? 0;

  return (
    <Stack gap={6}>
      <Breadcrumbs separator="›" fz="sm">
        {isTableType(type) ? (
          <AnchorLink to={TABLE_PATHS[type]}>{typeMeta.label_plural}</AnchorLink>
        ) : (
          // Records without a table: the type only.
          <span>{typeMeta.label_plural}</span>
        )}
        <bdi>{item.label}</bdi>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-start" gap="sm">
        <Stack gap={6}>
          <Title order={1} td={deleted ? 'line-through' : undefined}>
            <bdi>{item.label}</bdi>
          </Title>
          <Group gap={6} aria-label="Status">
            {isVerificationStatus(status) && (
              <Badge
                variant="outline"
                color="gray"
                title="Verification status of the record"
                leftSection={
                  <span aria-hidden>
                    <VerificationDot status={status} size={8} />
                  </span>
                }
              >
                {termLabel(vocab, 'verification_status', status)}
              </Badge>
            )}
            {clusterField && cluster !== null && <VocabBadge vocabulary={clusterField.vocabulary} code={cluster} />}
            <ScopeBadge item={item} typeMeta={typeMeta} />
            {deleted && (
              <Badge color="red" variant="filled">
                deleted
              </Badge>
            )}
            <Badge variant="default" title="Version">
              v{item.version}
            </Badge>
          </Group>
        </Stack>
        <Group gap="xs">
          {!editing && (
            <WriteButton
              leftSection={<IconPencil size={14} />}
              disabled={deleted}
              title={deleted ? 'Undelete the record to edit it.' : undefined}
              onClick={onEdit}
            >
              Edit
            </WriteButton>
          )}
          {deleted ? (
            <WriteButton variant="light" leftSection={<IconRestore size={14} />} onClick={onUndelete}>
              Undelete
            </WriteButton>
          ) : (
            <WriteButton
              variant="light"
              color="red"
              leftSection={<IconTrash size={14} />}
              disabled={editing}
              onClick={onDelete}
            >
              Delete
            </WriteButton>
          )}
          <CopyLinkButton url={`${window.location.origin}${detailHref(type, item.id)}`} />
          <Button
            variant={commentsOpen ? 'light' : 'default'}
            leftSection={<IconMessage size={14} />}
            aria-pressed={commentsOpen}
            onClick={onToggleComments}
          >
            Comments{openComments > 0 ? ` (${openComments} open)` : ''}
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}
