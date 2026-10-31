// The links panel of a document (docs/UI.md §8.7): each link with origin,
// state, matched aliases, match count and snippet; suggested links have
// Confirm and Reject, automatic links are never removed, manual links have
// Remove; "Add link…" adds a confirmed manual link. Each action sends PATCH
// with the full `links` list in which only that link changed (channel ui).
// "Tag now" asks the tagger for suggestions.
import { Badge, Button, Group, Modal, Stack, Table, Text, Title } from '@mantine/core';
import { IconCheck, IconPlus, IconTrash, IconX } from '@tabler/icons-react';
import { useState } from 'react';

import { usePatchEntity } from '../../api/queries';
import type { Item, JsonObject } from '../../api/types';
import { EntityLink } from '../EntityLink';
import { notifyError, notifySuccess } from '../feedback';
import { RefSelect } from '../fields/inputs/RefSelect';
import { asDocLinks, linkActions, linksAfter, linksWithAdded, type LinkAction } from './doc-links';
import { TagNowButton } from './TagNowButton';

const ACTION_LABELS: Record<LinkAction, string> = { confirm: 'Confirm', reject: 'Reject', remove: 'Remove' };
const ACTION_ICONS: Record<LinkAction, typeof IconCheck> = { confirm: IconCheck, reject: IconX, remove: IconTrash };
const STATE_COLORS = { suggested: 'yellow', confirmed: 'green', rejected: 'gray' } as const;

export function DocumentLinksPanel({ item }: { item: Item }) {
  const patch = usePatchEntity('document');
  const [adding, setAdding] = useState(false);
  const [subject, setSubject] = useState<string | null>(null);
  const links = asDocLinks(item.fields.links);
  const deleted = item.deleted_at !== null;
  const labelOf = (id: string) => item.refs[`links.${id}`]?.label ?? id;

  const save = async (next: JsonObject[], message: string): Promise<boolean> => {
    try {
      await patch.mutateAsync({ id: item.id, changes: { links: next }, note: null });
      notifySuccess(message);
      return true;
    } catch (error) {
      notifyError(error, 'Could not change the links');
      return false;
    }
  };

  return (
    <Stack gap={4} component="section" aria-label="Document links">
      <Group justify="space-between" gap="xs">
        <Group gap="xs" align="baseline">
          <Title order={3}>Links</Title>
          <Text span size="sm" c="dimmed">
            {links.length}
          </Text>
        </Group>
        <Group gap="xs">
          <TagNowButton documentId={item.id} disabled={deleted} />
          <Button
            size="xs"
            variant="subtle"
            leftSection={<IconPlus size={14} />}
            disabled={deleted}
            onClick={() => {
              setSubject(null);
              setAdding(true);
            }}
          >
            Add link…
          </Button>
        </Group>
      </Group>
      {links.length === 0 ? (
        <Text size="sm" c="dimmed">
          No links yet. “Tag now” suggests the projects and services whose aliases occur in the text.
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={760}>
          <Table withTableBorder>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Subject</Table.Th>
                <Table.Th>Origin</Table.Th>
                <Table.Th>State</Table.Th>
                <Table.Th>Matched aliases</Table.Th>
                <Table.Th ta="right">Matches</Table.Th>
                <Table.Th>Snippet</Table.Th>
                <Table.Th>Actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {links.map((link) => {
                const ref = item.refs[`links.${link.subject_id}`];
                return (
                  <Table.Tr key={link.subject_id}>
                    <Table.Td>
                      <EntityLink id={link.subject_id} label={ref?.label} type={ref?.type} deleted={ref?.deleted} />
                    </Table.Td>
                    <Table.Td>
                      <Badge size="xs" variant="outline" color="gray">
                        {link.origin === 'auto' ? 'automatic' : 'manual'}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Badge size="xs" variant="light" color={STATE_COLORS[link.state]}>
                        {link.state}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <bdi>{(link.matched_aliases ?? []).join('; ')}</bdi>
                    </Table.Td>
                    <Table.Td ta="right">{link.match_count ?? ''}</Table.Td>
                    <Table.Td>
                      {link.snippet && (
                        <Text size="xs" dir="auto" lineClamp={3} title={link.snippet}>
                          {link.snippet}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        {linkActions(link).map((action) => {
                          const Icon = ACTION_ICONS[action];
                          return (
                            <Button
                              key={action}
                              size="compact-xs"
                              variant={action === 'confirm' ? 'light' : 'subtle'}
                              color={action === 'confirm' ? 'green' : 'red'}
                              leftSection={<Icon size={12} />}
                              disabled={deleted || patch.isPending}
                              aria-label={`${ACTION_LABELS[action]} the link to ${labelOf(link.subject_id)}`}
                              onClick={() =>
                                void save(
                                  linksAfter(links, link.subject_id, action),
                                  `${ACTION_LABELS[action]}: link to ${labelOf(link.subject_id)}.`,
                                )
                              }
                            >
                              {ACTION_LABELS[action]}
                            </Button>
                          );
                        })}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <Modal
        opened={adding}
        onClose={() => {
          setAdding(false);
        }}
        title="Add a link"
      >
        <Stack gap="sm">
          <RefSelect
            label="Project or service"
            types={['project', 'service']}
            value={subject}
            excludeIds={links.map((link) => link.subject_id)}
            required
            onChange={setSubject}
          />
          <Group justify="flex-end" gap="xs">
            <Button
              variant="default"
              onClick={() => {
                setAdding(false);
              }}
            >
              Cancel
            </Button>
            <Button
              loading={patch.isPending}
              disabled={subject === null}
              onClick={() => {
                if (subject === null) return;
                const next = linksWithAdded(links, subject);
                if (next === null) {
                  notifyError(new Error('This subject is linked already.'));
                  return;
                }
                void save(next, 'Added a confirmed link.').then((saved) => {
                  if (saved) setAdding(false);
                });
              }}
            >
              Add link
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
