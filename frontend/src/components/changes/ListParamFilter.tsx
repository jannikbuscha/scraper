// A multi-select over one comma-separated list parameter of the page URL
// (the feed, runs and review filters). Every change returns to page 1.
import { MultiSelect } from '@mantine/core';

import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';
import { listParam, withListParam } from './feed-query';

export interface ParamOption {
  value: string;
  label: string;
}

export interface ListParamFilterProps {
  param: string;
  label: string;
  options: readonly ParamOption[];
  width: number;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
}

export function ListParamFilter({ param, label, options, width, search, setSearch }: ListParamFilterProps) {
  const values = listParam(search, param);
  // Values from a shared URL stay selectable even if the option list lacks them.
  const data = [
    ...options,
    ...values.filter((value) => !options.some((option) => option.value === value)).map((value) => ({ value, label: value })),
  ];
  return (
    <MultiSelect
      size="xs"
      w={width}
      label={label}
      placeholder={values.length === 0 ? 'Any' : undefined}
      data={data}
      value={values}
      searchable
      clearable
      onChange={(next) => {
        setSearch((previous) => withListParam(previous, param, next));
      }}
      comboboxProps={{ withinPortal: true }}
    />
  );
}
