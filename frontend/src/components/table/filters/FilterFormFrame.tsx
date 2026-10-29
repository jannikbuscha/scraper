import { Button, Group, Stack, Text } from '@mantine/core';
import type { ReactNode, SubmitEvent } from 'react';

import type { FieldSpec } from '../../../api/types';

/** Props of every filter form: the URL's raw `<op>:<value>` in, a new one (or null) out. */
export interface FilterFormProps {
  field: FieldSpec;
  raw: string | undefined;
  onApply: (raw: string | null) => void;
}

interface FilterFormFrameProps {
  title: string;
  children: ReactNode;
  onApply: () => void;
  onClear: () => void;
  applyDisabled?: boolean;
}

export function FilterFormFrame({ title, children, onApply, onClear, applyDisabled = false }: FilterFormFrameProps) {
  const submit = (event: SubmitEvent) => {
    event.preventDefault();
    if (!applyDisabled) onApply();
  };
  return (
    <form onSubmit={submit} aria-label={`Filter ${title}`}>
      <Stack gap="xs" w={290}>
        <Text fw={600} size="sm">
          {title}
        </Text>
        {children}
        <Group justify="space-between" mt={4}>
          <Button variant="subtle" color="gray" onClick={onClear}>
            Clear
          </Button>
          <Button type="submit" disabled={applyDisabled}>
            Apply
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
