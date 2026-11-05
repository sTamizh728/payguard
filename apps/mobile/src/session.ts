import {api, AssistantReply, PendingAction} from './api';
import {getPublicKey, playSound, securityStatus, signConfirmation} from './native';
import {TabName} from './components/TabBar';

export type Account = {
  token: string;
  email: string;
  fullName: string | null;
  isOwner: boolean;
};

export type LiveAlert = {
  id: number;
  kind: string;
  text: string;
  created_at: string;
};

export type Session = {
  account: Account | null;
  liveAlerts: LiveAlert[];
  tamil: boolean;
  setTamil: (tamil: boolean) => void;
  logout: (message?: string) => void;
  goTo: (tab: TabName) => void;
  handleError: (error: unknown) => string;
};

export const t = (tamil: boolean, en: string, ta: string) => (tamil ? ta : en);

/**
 * Make sure the server knows this phone's fingerprint/PIN key. Call right
 * after login: replacing a key needs a fresh login.
 */
export const setUpPhoneSecurity = async (token: string) => {
  const local = await securityStatus();
  if (!local.available) {
    return local.reason;
  }

  const publicKey = await getPublicKey();
  await api('/api/security/device-key', token, {body: {public_key: publicKey}});
  return null;
};

/**
 * Fingerprint / face / PIN, then send the signature with the Confirm.
 * Throws if the person cancels the prompt (nothing is sent then).
 */
export const confirmWithSecurity = async (
  token: string,
  action: PendingAction,
): Promise<AssistantReply> => {
  const signature = await signConfirmation(action.id, action.summary);
  const reply = await api<AssistantReply>('/api/chat/confirm', token, {
    body: {action_id: action.id, signature},
  });
  playSound(reply.event);
  return reply;
};
