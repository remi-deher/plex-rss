import { mount } from '@vue/test-utils';
import { h } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useRealtime } from './events';

describe('useRealtime', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('coalesces bursts and keeps the latest targeted payload', async () => {
    vi.useFakeTimers();
    const callback = vi.fn();
    const Host = {
      setup() {
        useRealtime(['request.updated'], callback, {
          debounceMs: 100,
          refreshOnVisible: false,
        });
        return () => h('div');
      },
    };
    const wrapper = mount(Host);

    window.dispatchEvent(new CustomEvent('plexarr:request.updated', { detail: { request_id: 1 } }));
    window.dispatchEvent(new CustomEvent('plexarr:request.updated', { detail: { request_id: 2 } }));
    await vi.advanceTimersByTimeAsync(99);
    expect(callback).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith('request.updated', { request_id: 2 });

    wrapper.unmount();
  });
});
