// App shell (root route): header with brand, global search, author menu and
// navigation; provides the vocabulary index and the author modal.
import { AppShell, Group } from '@mantine/core';
import { Link, Outlet } from '@tanstack/react-router';
import { useCallback, useMemo, useState } from 'react';

import { useMeta, useVocab } from '../../api/queries';
import { AuthorModalContext } from '../../hooks/useAuthor';
import { VocabIndexContext } from '../../hooks/useVocabIndex';
import { readStoredAuthor, rememberReadOnly, shouldAskForAuthor } from '../../lib/author';
import { buildVocabIndex } from '../../lib/vocab';
import { AuthorMenu } from './AuthorMenu';
import { AuthorModal } from './AuthorModal';
import { GlobalSearch } from './GlobalSearch';
import classes from './layout.module.css';
import { MainNav } from './MainNav';

/** Header height (two rows); sticky table headers sit just below it. */
export const HEADER_HEIGHT = 86;

export function AppLayout() {
  const meta = useMeta();
  const vocab = useVocab();
  const vocabIndex = useMemo(() => buildVocabIndex(vocab.data?.vocabularies ?? []), [vocab.data]);
  // On the first visit (no stored name, no read-only choice in this browser
  // session) the app asks who you are.
  const [authorModalOpen, setAuthorModalOpen] = useState(shouldAskForAuthor);
  const openAuthorModal = useCallback(() => {
    setAuthorModalOpen(true);
  }, []);

  return (
    <AuthorModalContext.Provider value={openAuthorModal}>
      <VocabIndexContext.Provider value={vocabIndex}>
        <a href="#main" className={classes.skipLink}>
          Skip to content
        </a>
        <AppShell header={{ height: HEADER_HEIGHT }} padding="md">
          <AppShell.Header>
            <Group className={classes.headerRow} justify="space-between" wrap="nowrap">
              <Link to="/" className={classes.brand}>
                MDT Portfolio
              </Link>
              <Group gap="sm" wrap="nowrap">
                <GlobalSearch />
                <AuthorMenu />
              </Group>
            </Group>
            <MainNav />
          </AppShell.Header>
          <AppShell.Main id="main" tabIndex={-1} className={classes.main}>
            <Outlet />
          </AppShell.Main>
        </AppShell>
        <AuthorModal
          opened={authorModalOpen}
          onClose={() => {
            // Closed without a name ("Continue read-only", Escape, ×): remembered for the session.
            if (readStoredAuthor() === null) rememberReadOnly();
            setAuthorModalOpen(false);
          }}
          teamMembers={meta.data?.team_members ?? []}
        />
      </VocabIndexContext.Provider>
    </AuthorModalContext.Provider>
  );
}
