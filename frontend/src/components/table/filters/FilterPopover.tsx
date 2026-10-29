// Filter button of a header cell with an active-state dot; the popover form
// depends on the field's filter kind (docs/UI.md §3).
import { ActionIcon, Indicator, Popover } from '@mantine/core';
import { IconFilter } from '@tabler/icons-react';
import { useState, type ReactElement } from 'react';

import type { FieldSpec, FilterKind } from '../../../api/types';
import { getFilter, setFilter } from '../../../lib/query-string';
import { useTableContext } from '../TableContext';
import { BoolFilterForm } from './BoolFilterForm';
import { DateRangeFilterForm } from './DateRangeFilterForm';
import type { FilterFormProps } from './FilterFormFrame';
import { MultiselectFilterForm } from './MultiselectFilterForm';
import { NumberRangeFilterForm } from './NumberRangeFilterForm';
import { RefFilterForm } from './RefFilterForm';
import { TextFilterForm } from './TextFilterForm';

const FORMS: Record<FilterKind, (props: FilterFormProps) => ReactElement> = {
  text: TextFilterForm,
  multiselect: MultiselectFilterForm,
  date_range: DateRangeFilterForm,
  bool: BoolFilterForm,
  number_range: NumberRangeFilterForm,
  ref: RefFilterForm,
};

export function FilterPopover({ field }: { field: FieldSpec }) {
  const { search, setSearch } = useTableContext();
  const [opened, setOpened] = useState(false);
  if (!field.filter) return null;
  const Form = FORMS[field.filter];
  const raw = getFilter(search, field.name);
  const active = raw !== undefined;

  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-start" withArrow trapFocus returnFocus>
      <Popover.Target>
        <Indicator disabled={!active} size={7} offset={4} color="indigo" withBorder>
          <ActionIcon
            size="sm"
            variant={active ? 'light' : 'subtle'}
            color={active ? 'indigo' : 'gray'}
            aria-label={active ? `Filter ${field.label} (active)` : `Filter ${field.label}`}
            aria-expanded={opened}
            onClick={() => {
              setOpened((open) => !open);
            }}
          >
            <IconFilter size={14} />
          </ActionIcon>
        </Indicator>
      </Popover.Target>
      <Popover.Dropdown>
        {/* Mounted only while open: the form starts from the URL and facets load lazily. */}
        {opened && (
          <Form
            field={field}
            raw={raw}
            onApply={(next) => {
              setSearch((previous) => setFilter(previous, field.name, next));
              setOpened(false);
            }}
          />
        )}
      </Popover.Dropdown>
    </Popover>
  );
}
