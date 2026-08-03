import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import MediaRequestsTab from './MediaRequestsTab.vue';

const row = {
  id: 42,
  media_type: 'movie',
  status: 'failed',
  operational_status: 'failed',
  requested_by: 'Alice',
  requester_ids: ['alice'],
};

function render(admin) {
  return mount(MediaRequestsTab, {
    props: { admin, requests: [row], detail: {} },
    global: {
      stubs: {
        RequestStatusStepper: true,
        RequestMailHistory: true,
        RequesterList: true,
      },
    },
  });
}

describe('MediaRequestsTab', () => {
  it('ne montre aucune commande technique aux utilisateurs ordinaires', () => {
    const wrapper = render(false);

    expect(wrapper.find('.request-admin-actions').exists()).toBe(false);
    expect(wrapper.find('[aria-label="Relancer"]').exists()).toBe(false);
  });

  it('regroupe les commandes techniques dans Administration', () => {
    const wrapper = render(true);

    expect(wrapper.find('.request-admin-actions').exists()).toBe(true);
    expect(wrapper.find('.request-admin-actions').attributes('open')).toBeUndefined();
    expect(wrapper.find('[aria-label="Relancer"]').exists()).toBe(true);
  });
});
