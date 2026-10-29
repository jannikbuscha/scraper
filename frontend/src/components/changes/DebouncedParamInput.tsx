// A text input bound to one URL parameter, written 300 ms after typing stops
// (replacing the history entry). Another change of the parameter, e.g. the
// back button or "Clear filters", replaces the text.
import { TextInput } from '@mantine/core';
import { useDebouncedCallback } from '@mantine/hooks';
import { useState, type ReactNode } from 'react';

import type { SearchUpdate, SetSearchOptions } from '../../hooks/useUrlSearch';
import type { SearchRecord } from '../../lib/query-string';
import { withParam } from './feed-query';

interface DebouncedParamInputProps {
  param: string;
  label: string;
  search: SearchRecord;
  setSearch: (update: SearchUpdate, options?: SetSearchOptions) => void;
  placeholder?: string;
  width?: number;
  leftSection?: ReactNode;
}

export function DebouncedParamInput({
  param,
  label,
  search,
  setSearch,
  placeholder,
  width = 200,
  leftSection,
}: DebouncedParamInputProps) {
  const urlValue = search[param] ?? '';
  const [text, setText] = useState(urlValue);
  // The last value this input wrote or saw.
  const [synced, setSynced] = useState(urlValue);
  if (urlValue !== synced) {
    setSynced(urlValue);
    setText(urlValue);
  }
  const commit = useDebouncedCallback((value: string) => {
    setSynced(value.trim());
    setSearch((previous) => withParam(previous, param, value.trim()), { replace: true });
  }, 300);
  return (
    <TextInput
      size="xs"
      w={width}
      label={label}
      placeholder={placeholder}
      leftSection={leftSection}
      value={text}
      onChange={(event) => {
        setText(event.currentTarget.value);
        commit(event.currentTarget.value);
      }}
    />
  );
}
