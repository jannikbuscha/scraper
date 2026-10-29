// "Who are you?" (docs/UI.md §1.5): quick pick from the team list or recent
// names, or free text, validated exactly like the server.
import { Alert, Button, Chip, Group, Modal, Stack, Text, TextInput } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import { useState, type SubmitEvent } from 'react';

import { useAuthor } from '../../hooks/useAuthor';
import { readRecentAuthors, setAuthor, validateAuthor } from '../../lib/author';

interface AuthorModalProps {
  opened: boolean;
  onClose: () => void;
  teamMembers: readonly string[];
}

export function AuthorModal({ opened, onClose, teamMembers }: AuthorModalProps) {
  const author = useAuthor();
  return (
    <Modal opened={opened} onClose={onClose} title="Who are you?" size="md">
      {/* Mounted only while open, so the form starts from the stored name. */}
      {opened && <AuthorForm current={author} teamMembers={teamMembers} onDone={onClose} />}
    </Modal>
  );
}

interface AuthorFormProps {
  current: string | null;
  teamMembers: readonly string[];
  onDone: () => void;
}

function AuthorForm({ current, teamMembers, onDone }: AuthorFormProps) {
  const [input, setInput] = useState(current ?? '');
  const [touched, setTouched] = useState(false);
  const [recent] = useState(readRecentAuthors);
  const validation = validateAuthor(input);
  const quickPicks = [...new Set([...teamMembers, ...recent])].filter((name) => validateAuthor(name).ok);

  const save = (name: string) => {
    if (setAuthor(name).ok) onDone();
  };
  const onSubmit = (event: SubmitEvent) => {
    event.preventDefault();
    setTouched(true);
    if (validation.ok) save(validation.name);
  };

  return (
    <form onSubmit={onSubmit} noValidate>
      <Stack gap="md">
        <Alert variant="light" color="gray" icon={<IconInfoCircle size={18} />}>
          This app has no login. Your name is recorded with every change you make (attribution, not
          authentication) and is stored in this browser only.
        </Alert>
        {quickPicks.length > 0 && (
          <Stack gap={6}>
            <Text size="sm" fw={500}>
              Pick your name
            </Text>
            <Group gap={6}>
              {quickPicks.map((name) => (
                <Chip
                  key={name}
                  checked={name === current}
                  onChange={() => {
                    save(name);
                  }}
                  size="sm"
                  variant="outline"
                >
                  <bdi>{name}</bdi>
                </Chip>
              ))}
            </Group>
          </Stack>
        )}
        <TextInput
          label={quickPicks.length > 0 ? 'Or enter your name' : 'Your name'}
          value={input}
          maxLength={200}
          data-autofocus
          onChange={(event) => {
            setInput(event.currentTarget.value);
            setTouched(true);
          }}
          error={touched && !validation.ok ? validation.error : undefined}
        />
        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onDone}>
            {current ? 'Cancel' : 'Continue read-only'}
          </Button>
          <Button type="submit" disabled={!validation.ok}>
            Save name
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
