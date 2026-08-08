import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import RetentionDaysInput from './RetentionDaysInput.vue';

describe('RetentionDaysInput', () => {
  it('affiche la checkbox cochée et masque le champ numérique quand la valeur est null', () => {
    const wrapper = mount(RetentionDaysInput, { props: { modelValue: null } });

    expect(wrapper.get('input[type="checkbox"]').element.checked).toBe(true);
    expect(wrapper.find('input[type="number"]').exists()).toBe(false);
  });

  it('affiche la checkbox décochée et le champ numérique quand une valeur est définie', () => {
    const wrapper = mount(RetentionDaysInput, { props: { modelValue: 30 } });

    expect(wrapper.get('input[type="checkbox"]').element.checked).toBe(false);
    expect(wrapper.get('input[type="number"]').element.value).toBe('30');
  });

  it('émet null en cochant "Conserver indéfiniment"', async () => {
    const wrapper = mount(RetentionDaysInput, { props: { modelValue: 30 } });
    await wrapper.get('input[type="checkbox"]').setValue(true);

    expect(wrapper.emitted('update:modelValue')[0]).toEqual([null]);
  });

  it('restaure la dernière valeur saisie en décochant', async () => {
    const wrapper = mount(RetentionDaysInput, { props: { modelValue: 45 } });
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.setProps({ modelValue: null });
    await wrapper.get('input[type="checkbox"]').setValue(false);

    expect(wrapper.emitted('update:modelValue').at(-1)).toEqual([45]);
  });

  it("retombe sur defaultDays quand aucune valeur n'a jamais été saisie", async () => {
    const wrapper = mount(RetentionDaysInput, { props: { modelValue: null, defaultDays: 90 } });
    await wrapper.get('input[type="checkbox"]').setValue(false);

    expect(wrapper.emitted('update:modelValue')[0]).toEqual([90]);
  });
});
