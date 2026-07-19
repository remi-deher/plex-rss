<template>
  <div>
    <div class="markdown-toolbar" role="toolbar" aria-label="Mise en forme du modele">
      <select title="Niveau de titre" @change="setHeading($event.target.value);$event.target.value=''">
        <option value="">Titre</option><option value="1">Titre 1</option><option value="2">Titre 2</option><option value="3">Titre 3</option>
      </select>
      <button class="icon-button" title="Gras" @click="wrapSelection('**','**','texte en gras')"><Bold/></button>
      <button class="icon-button" title="Italique" @click="wrapSelection('*','*','texte en italique')"><Italic/></button>
      <button class="icon-button" title="Liste a puces" @click="prefixLines('- ')"><List/></button>
      <button class="icon-button" title="Liste numerotee" @click="prefixLines('1. ')"><ListOrdered/></button>
      <button class="icon-button" title="Citation" @click="prefixLines('> ')"><Quote/></button>
      <button class="icon-button" title="Lien" @click="insertLink"><LinkIcon/></button>
      <details v-if="variables.length" class="variable-picker">
        <summary><Braces/>Variables</summary>
        <div class="variable-menu">
          <button v-for="variable in variables" :key="variable.tag" type="button" @click="insertText(variable.tag)"><code>{{ variable.tag }}</code><span>{{ variable.description }}</span></button>
        </div>
      </details>
    </div>
    <textarea ref="editor" :value="modelValue" :rows="rows" class="code-editor" @input="$emit('update:modelValue', $event.target.value)"></textarea>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue';
import { Bold, Braces, Italic, Link as LinkIcon, List, ListOrdered, Quote } from '@lucide/vue';

const props = defineProps({
  modelValue: { type: String, default: '' },
  rows: { type: [String, Number], default: 10 },
  variables: { type: Array, default: () => [] },
});
const emit = defineEmits(['update:modelValue']);

const editor = ref(null);

function updateValue(value, start, end) {
  emit('update:modelValue', value);
  nextTick(() => {
    const target = editor.value;
    target?.focus();
    if (target) { target.selectionStart = start; target.selectionEnd = end; }
  });
}

function insertText(text) {
  const target = editor.value;
  if (!target) return;
  const start = target.selectionStart ?? target.value.length, end = target.selectionEnd ?? start;
  updateValue(target.value.slice(0, start) + text + target.value.slice(end), start + text.length, start + text.length);
}

function wrapSelection(prefix, suffix, placeholder) {
  const target = editor.value;
  if (!target) return;
  const start = target.selectionStart, end = target.selectionEnd, selected = target.value.slice(start, end) || placeholder;
  updateValue(target.value.slice(0, start) + prefix + selected + suffix + target.value.slice(end), start + prefix.length, start + prefix.length + selected.length);
}

function prefixLines(prefix) {
  const target = editor.value;
  if (!target) return;
  const start = target.selectionStart, end = target.selectionEnd, lineStart = target.value.lastIndexOf('\n', start - 1) + 1;
  let lineEnd = target.value.indexOf('\n', end);
  if (lineEnd < 0) lineEnd = target.value.length;
  const transformed = target.value.slice(lineStart, lineEnd).split('\n').map(line => prefix + line).join('\n');
  updateValue(target.value.slice(0, lineStart) + transformed + target.value.slice(lineEnd), lineStart, lineStart + transformed.length);
}

function setHeading(level) {
  const target = editor.value;
  if (!target || !level) return;
  const position = target.selectionStart, lineStart = target.value.lastIndexOf('\n', position - 1) + 1;
  let lineEnd = target.value.indexOf('\n', position);
  if (lineEnd < 0) lineEnd = target.value.length;
  const line = target.value.slice(lineStart, lineEnd).replace(/^#{1,6}\s*/, ''), replacement = `${'#'.repeat(Number(level))} ${line}`;
  updateValue(target.value.slice(0, lineStart) + replacement + target.value.slice(lineEnd), lineStart + replacement.length, lineStart + replacement.length);
}

function insertLink() {
  const target = editor.value;
  if (!target) return;
  const start = target.selectionStart, end = target.selectionEnd, selected = target.value.slice(start, end) || 'texte du lien';
  const url = prompt('URL du lien :', 'https://');
  if (!url) return;
  const value = `[${selected}](${url})`;
  updateValue(target.value.slice(0, start) + value + target.value.slice(end), start + value.length, start + value.length);
}
</script>
