// Ré-exports conservés pour les composants de la page Bibliothèque, qui parlent en
// « statuts » et « types » de liste. La définition des libellés vit dans @/utils/labels,
// celle du proxy d'images dans @/utils/mediaImage.
export {
  KIND_STATUSES,
  REQUEST_STATUSES as STATUSES,
  mediaTypePluralLabel as typeLabel,
  requestStatusLabel as statusLabel,
} from '@/utils/labels';
export { proxyUrl } from '@/utils/mediaImage';

export const TYPES = ['movie', 'show'];
