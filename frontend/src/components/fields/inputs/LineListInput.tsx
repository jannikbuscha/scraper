// URL and string lists edited as one item per line (docs/UI.md §4.1).
import { Textarea } from '@mantine/core';
import { useState, type ReactNode } from 'react';

import { valuesEqual } from '../../../lib/diff';

export const parseLines = (text: string): string[] =>
  text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '');

interface LineListInputProps {
  value: string[];
  onChange: (value: string[]) => void;
  label: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  required?: boolean;
  size?: 'xs' | 'sm';
}

export function LineListInput({ value, onChange, size = 'sm', ...rest }: LineListInputProps) {
  // The raw text keeps blank lines while typing; it is replaced only when the
  // value changes from outside (e.g. a reset).
  const [text, setText] = useState(value.join('\n'));
  const [lastValue, setLastValue] = useState(value);
  if (!valuesEqual(value, lastValue)) {
    setLastValue(value);
    setText(value.join('\n'));
  }
  return (
    <Textarea
      {...rest}
      size={size}
      value={text}
      autosize
      minRows={2}
      maxRows={10}
      onChange={(event) => {
        const raw = event.currentTarget.value;
        const next = parseLines(raw);
        setText(raw);
        setLastValue(next);
        onChange(next);
      }}
    />
  );
}
