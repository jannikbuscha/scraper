// Saved views (docs/UI.md §3): listed from GET /api/entities/saved_view,
// applied by navigation, saved and (soft-)deleted. The list scrolls inside
// the dropdown; "Save current view…" stays below it, always visible.
import {
  ActionIcon,
  Button,
  Divider,
  Group,
  Loader,
  Popover,
  ScrollArea,
  Stack,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { IconBookmark, IconCheck, IconChevronDown, IconDeviceFloppy, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';

import { useSavedViews } from '../../api/queries';
import type { Item } from '../../api/types';
import { asString } from '../../lib/format';
import { canonicalQuery, DETAIL_PAGE_PARAMS, searchFromQuery } from '../../lib/query-string';
import { errorMessage } from '../feedback';
import { DeleteViewModal } from './DeleteViewModal';
import { SaveViewModal } from './SaveViewModal';
import classes from './toolbar.module.css';
import { useTableContext } from './TableContext';

/** The view list scrolls beyond this height; the save action below it stays visible. */
export const VIEW_LIST_MAX_HEIGHT = 'min(60vh, 420px)';

export function SavedViewsMenu() {
  const { type, search, setSearch } = useTableContext();
  const views = useSavedViews(type);
  const [opened, setOpened] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<Item | null>(null);
  // A view stores the whole state except the page number.
  const current = canonicalQuery(search, (key) => key === 'page' || DETAIL_PAGE_PARAMS.has(key));

  return (
    <>
      <Popover opened={opened} onChange={setOpened} position="bottom-end" withArrow>
        <Popover.Target>
          <Button
            variant="default"
            leftSection={<IconBookmark size={14} />}
            rightSection={<IconChevronDown size={14} />}
            aria-expanded={opened}
            onClick={() => {
              setOpened((open) => !open);
            }}
          >
            Saved views
          </Button>
        </Popover.Target>
        <Popover.Dropdown p={6}>
          <Stack gap={2} w={320}>
            {/* "contain": scrolling past the end of the list does not scroll the page,
                which would move the button out of view and close the dropdown. */}
            <ScrollArea.Autosize mah={VIEW_LIST_MAX_HEIGHT} type="auto" offsetScrollbars overscrollBehavior="contain">
              {views.isPending && <Loader size="xs" m="xs" />}
              {views.isError && (
                <Text size="xs" c="red" p="xs">
                  {errorMessage(views.error)}
                </Text>
              )}
              {views.data?.items.length === 0 && (
                <Text size="sm" c="dimmed" p="xs">
                  No saved views yet.
                </Text>
              )}
              <Stack gap={2} role="list" aria-label="Saved views">
                {views.data?.items.map((view) => {
                  const query = asString(view.fields.query) ?? '';
                  const description = asString(view.fields.description);
                  const active = query === current;
                  return (
                    <Group key={view.id} gap={4} wrap="nowrap" role="listitem">
                      <UnstyledButton
                        className={classes.menuRow}
                        aria-current={active ? 'true' : undefined}
                        onClick={() => {
                          setSearch(searchFromQuery(query));
                          setOpened(false);
                        }}
                      >
                        <Group gap={6} wrap="nowrap" align="flex-start">
                          <IconCheck size={14} className={classes.check} data-active={active} aria-hidden />
                          <div>
                            <Text size="sm">
                              <bdi>{asString(view.fields.name) ?? view.label}</bdi>
                            </Text>
                            {description && (
                              <Text size="xs" c="dimmed" lineClamp={2}>
                                <bdi>{description}</bdi>
                              </Text>
                            )}
                          </div>
                        </Group>
                      </UnstyledButton>
                      <ActionIcon
                        aria-label={`Delete saved view ${asString(view.fields.name) ?? view.label}`}
                        onClick={() => {
                          setOpened(false);
                          setDeleting(view);
                        }}
                      >
                        <IconTrash size={14} />
                      </ActionIcon>
                    </Group>
                  );
                })}
              </Stack>
            </ScrollArea.Autosize>
            <Divider my={4} />
            <Button
              variant="subtle"
              justify="flex-start"
              leftSection={<IconDeviceFloppy size={14} />}
              onClick={() => {
                setOpened(false);
                setSaving(true);
              }}
            >
              Save current view…
            </Button>
          </Stack>
        </Popover.Dropdown>
      </Popover>
      <SaveViewModal
        opened={saving}
        onClose={() => {
          setSaving(false);
        }}
        type={type}
        query={current}
      />
      <DeleteViewModal
        view={deleting}
        onClose={() => {
          setDeleting(null);
        }}
      />
    </>
  );
}
