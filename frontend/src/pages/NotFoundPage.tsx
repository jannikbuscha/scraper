import { Stack, Text, Title } from '@mantine/core';

import { AnchorLink } from '../components/AnchorLink';

export function NotFoundPage() {
  return (
    <Stack gap="xs" maw={560}>
      <Title order={1}>Page not found</Title>
      <Text>This address does not match any page of the app.</Text>
      <AnchorLink to="/">Go to the overview</AnchorLink>
    </Stack>
  );
}
