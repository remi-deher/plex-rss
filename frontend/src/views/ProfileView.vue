<template>
  <div class="page">
    <header class="page-head">
      <div><h1>Profil</h1><p>Securite du compte et methodes de connexion.</p></div>
    </header>
    <p v-if="error" class="notice error-text">{{ error }}</p>
    <p v-if="message" class="notice success-text">{{ message }}</p>
    <div class="settings-grid">
      <section class="panel form-section">
        <h2>Compte</h2>
        <div><strong>{{ identity?.plex_user_id || identity?.username }}</strong><p>{{ identity?.role }}</p></div>
        <label>Nouveau mot de passe<input v-model="password" type="password" minlength="8" autocomplete="new-password"></label>
        <button class="primary" :disabled="!password || busy" @click="changePassword"><KeyRound/>Modifier</button>
      </section>
      <section class="panel form-section">
        <h2>Double authentification</h2>
        <p v-if="totpSecret">Secret : <code>{{ totpSecret }}</code></p>
        <button v-if="!totpSecret" class="secondary" :disabled="busy" @click="setupTotp"><ShieldCheck/>Configurer</button>
        <template v-else>
          <label>Code a 6 chiffres<input v-model="totpCode" inputmode="numeric" maxlength="6"></label>
          <button class="primary" :disabled="totpCode.length !== 6 || busy" @click="enableTotp">Activer</button>
        </template>
        <button class="secondary danger" :disabled="busy" @click="disableTotp">Desactiver le TOTP</button>
      </section>
      <section class="panel form-section">
        <div class="panel-head"><h2>Passkeys</h2><button class="icon-button" title="Actualiser" @click="loadPasskeys"><RefreshCw/></button></div>
        <div v-for="key in passkeys" :key="key.credential_id" class="inline-row">
          <span>{{ key.name }}</span><button class="icon-button danger" title="Supprimer" @click="deletePasskey(key)"><Trash2/></button>
        </div>
        <p v-if="!passkeys.length">Aucune passkey enregistree.</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { KeyRound, RefreshCw, ShieldCheck, Trash2 } from "@lucide/vue";
import { api } from "@/api";

const identity=ref(null),password=ref(''),totpSecret=ref(''),totpCode=ref(''),passkeys=ref([]),busy=ref(false),error=ref(''),message=ref('');
function notify(text){message.value=text;error.value=''}
async function load(){try{identity.value=await api('/api/session');await loadPasskeys()}catch(e){error.value=e.message}}
async function loadPasskeys(){if(!identity.value?.id)return;try{passkeys.value=await api(`/api/users/${identity.value.id}/passkeys`)}catch(e){error.value=e.message}}
async function changePassword(){busy.value=true;try{await api(`/api/users/${identity.value.id}/password`,{method:'POST',body:JSON.stringify({password:password.value})});password.value='';notify('Mot de passe modifie.')}catch(e){error.value=e.message}finally{busy.value=false}}
async function setupTotp(){busy.value=true;try{const data=await api(`/api/users/${identity.value.id}/totp/setup`,{method:'POST'});totpSecret.value=data.secret;notify('Ajoutez ce secret dans votre application d’authentification.')}catch(e){error.value=e.message}finally{busy.value=false}}
async function enableTotp(){busy.value=true;try{await api(`/api/users/${identity.value.id}/totp/enable`,{method:'POST',body:JSON.stringify({code:totpCode.value})});totpSecret.value='';totpCode.value='';notify('Double authentification activee.')}catch(e){error.value=e.message}finally{busy.value=false}}
async function disableTotp(){busy.value=true;try{await api(`/api/users/${identity.value.id}/totp`,{method:'DELETE'});totpSecret.value='';notify('Double authentification desactivee.')}catch(e){error.value=e.message}finally{busy.value=false}}
async function deletePasskey(key){try{await api(`/api/users/${identity.value.id}/passkeys/${encodeURIComponent(key.credential_id)}`,{method:'DELETE'});await loadPasskeys()}catch(e){error.value=e.message}}
onMounted(load);
</script>
