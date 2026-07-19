<template>
  <div class="settings-grid">
    <div class="settings-cards span-two">
      <DownloadClientsCard/>

      <SettingsCard title="Regles torrent" :icon="Magnet" status="active" :collapsible="false">
        <label>Confirmation de disponibilite
          <select v-model="form.availability_confirmation_mode">
            <option value="arr">Import Sonarr/Radarr</option>
            <option value="plex">Presence Plex obligatoire</option>
            <option value="hybrid">Hybride : Plex puis repli *arr</option>
          </select>
        </label>
        <label v-if="form.availability_confirmation_mode === 'hybrid'">Delai du repli *arr (minutes)
          <input v-model.number="form.availability_confirmation_timeout_minutes" type="number" min="1">
        </label>
        <label>Mots requis<input v-model="form.torrent_required_keywords"></label>
        <label>Mots interdits<input v-model="form.torrent_forbidden_keywords"></label>
        <label>Taille minimale (Go)<input v-model.number="form.torrent_min_size_gb" type="number"></label>
        <label>Taille maximale (Go)<input v-model.number="form.torrent_max_size_gb" type="number"></label>
        <label>Ratio limite<input v-model.number="form.torrent_ratio_limit" type="number" step="0.1"></label>
        <label>Duree de seed (h)<input v-model.number="form.torrent_seed_time_limit_hours" type="number"></label>
        <label class="check"><input v-model="form.torrent_auto_delete_files" type="checkbox"> Supprimer les fichiers apres seed, uniquement apres verification Plex</label>
      </SettingsCard>
    </div>
  </div>
</template>
<script setup>
import { Magnet } from '@lucide/vue';
import { form } from '@/settingsForm';
import SettingsCard from './SettingsCard.vue';
import DownloadClientsCard from './connections/DownloadClientsCard.vue';
</script>
