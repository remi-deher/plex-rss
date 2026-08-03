import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DashboardView from './DashboardView.vue';

const apiMock = vi.fn();
const streamEventsMock = vi.fn();

vi.mock('@/api', () => ({
  api: (...args) => apiMock(...args),
  cachedResource: (_key, _ttl, loader) => ({ cached: null, refresh: loader() }),
  streamEvents: (...args) => streamEventsMock(...args),
}));
vi.mock('@/cache', () => ({
  readCacheEntry: () => null,
  writeCache: vi.fn(),
}));
vi.mock('@/events', () => ({ useRealtime: vi.fn() }));
vi.mock('@/composables/usePolling', () => ({ usePolling: vi.fn() }));

function mountView() {
  return mount(DashboardView, {
    global: {
      stubs: {
        PageHeader: true,
        UiFeedback: true,
        OnboardingChecklist: true,
        DashboardActionCenter: true,
        MetricGrid: true,
        LiveSessionsPanel: true,
        DownloadQueuePanel: true,
        RecentJobsPanel: true,
        ScanStatusPanel: true,
        ActivityChartPanel: true,
        RecentlyAvailablePanel: true,
        UpcomingReleasesPanel: true,
        RequestsBreakdownPanel: true,
        TopRequestedPanel: true,
        ActiveUsersPanel: true,
        RecentNotificationsPanel: true,
        DiskSpacePanel: true,
      },
    },
  });
}

describe('DashboardView supervision', () => {
  beforeEach(() => {
    localStorage.clear();
    apiMock.mockReset();
    streamEventsMock.mockReset();
    streamEventsMock.mockImplementation(async (_path, apply) => {
      apply({ pending: [], next_poll: { next_run_seconds: 30 } });
    });
    apiMock.mockImplementation(async path => {
      if (path === '/api/arr/queue' || path === '/api/disk-space') return [];
      if (path === '/api/playback/live') return { active: [] };
      if (path === '/api/health') return { services: {} };
      if (path.startsWith('/api/dashboard/snapshot')) return {};
      return {};
    });
  });

  it('differe les appels de supervision jusqu a la premiere ouverture', async () => {
    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.get('details').element.open).toBe(false);
    expect(streamEventsMock.mock.calls[0][0]).not.toContain('counts');
    expect(streamEventsMock.mock.calls[0][0]).not.toContain('top_requested');
    expect(apiMock).not.toHaveBeenCalledWith('/api/health');
    expect(apiMock).not.toHaveBeenCalledWith('/api/disk-space');

    const details = wrapper.get('details');
    details.element.open = true;
    await details.trigger('toggle');
    await flushPromises();

    expect(localStorage.getItem('dashboard.supervisionOpen')).toBe('true');
    expect(apiMock).toHaveBeenCalledWith('/api/health');
    expect(apiMock).toHaveBeenCalledWith('/api/disk-space');
    expect(apiMock).toHaveBeenCalledWith(
      '/api/dashboard/snapshot?sections=counts,top_requested,by_user,notifications',
    );
  });
});
