// Column chooser (docs/UI.md §3): checkboxes over the type's fields that have
// a value per list row (`exportable`; not the detail-only document text),
// grouped as in meta.groups, system columns included; stored in `cols`,
// default = the in_list fields.
import { Button, Checkbox, Group, Popover, ScrollArea, Stack, Text } from '@mantine/core';
import { IconChevronDown, IconColumns } from '@tabler/icons-react';

import { columnChoice, getColumns, withColumns } from '../../lib/query-string';
import { useTableContext } from './TableContext';

export function ColumnsMenu() {
  const { meta, typeMeta, search, setSearch } = useTableContext();
  const { known, defaults } = columnChoice(typeMeta.fields);
  const offered = typeMeta.fields.filter((field) => field.exportable);
  const visible = new Set(getColumns(search, known, defaults));
  const groupKeys = new Set(meta.groups.map((group) => group.key));
  const groups = [
    ...meta.groups.map((group) => ({
      key: group.key,
      label: group.label,
      fields: offered.filter((field) => field.group === group.key),
    })),
    { key: 'other', label: 'Other', fields: offered.filter((field) => !groupKeys.has(field.group)) },
  ].filter((group) => group.fields.length > 0);

  const toggle = (name: string, checked: boolean) => {
    const next = new Set(visible);
    if (checked) next.add(name);
    else next.delete(name);
    setSearch((previous) => withColumns(previous, known.filter((n) => next.has(n)), defaults));
  };

  return (
    <Popover position="bottom-end" withArrow trapFocus>
      <Popover.Target>
        <Button variant="default" leftSection={<IconColumns size={14} />} rightSection={<IconChevronDown size={14} />}>
          Columns
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs" w={300}>
          <ScrollArea.Autosize mah={420} type="auto" offsetScrollbars>
            <Stack gap="sm">
              {groups.map((group) => (
                <Stack key={group.key} gap={4} role="group" aria-label={group.label}>
                  <Text size="xs" fw={700} c="dimmed" tt="uppercase">
                    {group.label}
                  </Text>
                  {group.fields.map((field) => (
                    <Checkbox
                      key={field.name}
                      size="xs"
                      label={field.label}
                      checked={visible.has(field.name)}
                      // At least one column stays visible.
                      disabled={visible.has(field.name) && visible.size === 1}
                      onChange={(event) => {
                        toggle(field.name, event.currentTarget.checked);
                      }}
                    />
                  ))}
                </Stack>
              ))}
            </Stack>
          </ScrollArea.Autosize>
          <Group justify="flex-end">
            <Button
              variant="subtle"
              onClick={() => {
                setSearch((previous) => withColumns(previous, defaults, defaults));
              }}
            >
              Reset to default
            </Button>
          </Group>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
