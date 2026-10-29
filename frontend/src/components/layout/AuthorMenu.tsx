// Header button: shows the author name; clicking it changes the name.
import { Button, Tooltip } from '@mantine/core';
import { IconUser, IconUserQuestion } from '@tabler/icons-react';

import { useAuthor, useOpenAuthorModal } from '../../hooks/useAuthor';

export function AuthorMenu() {
  const author = useAuthor();
  const openAuthorModal = useOpenAuthorModal();
  if (author === null) {
    return (
      <Button size="xs" color="orange" variant="light" leftSection={<IconUserQuestion size={16} />} onClick={openAuthorModal}>
        Set your name
      </Button>
    );
  }
  return (
    <Tooltip label="Recorded as the author of your changes. Click to change.">
      <Button
        size="xs"
        variant="subtle"
        color="gray"
        leftSection={<IconUser size={16} />}
        onClick={openAuthorModal}
        aria-label={`Author: ${author}. Change name`}
        maw={220}
      >
        <bdi>{author}</bdi>
      </Button>
    </Tooltip>
  );
}
