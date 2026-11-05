import {NativeModules} from 'react-native';

// PayGuard's own Android module (android/app/.../PayGuardNativeModule.kt).
const Native = NativeModules.PayGuardNative as
  | {
      securityStatus(): Promise<{
        available: boolean;
        reason: string;
        hasKey: boolean;
      }>;
      getPublicKey(): Promise<string>;
      resetKey(): Promise<boolean>;
      signWithAuth(
        payload: string,
        title: string,
        subtitle: string,
      ): Promise<string>;
      playSound(name: string): void;
      speak(text: string, language: string): Promise<boolean>;
      stopSpeaking(): void;
    }
  | undefined;

export type SoundName =
  | 'payment_sent'
  | 'refund_done'
  | 'money_received'
  | 'request_sent'
  | 'failed'
  | 'confirm_needed'
  | 'listening'
  | 'stopped';

export const playSound = (name: SoundName | string | null | undefined) => {
  if (name) {
    Native?.playSound(name);
  }
};

export const speak = async (text: string, language: string) =>
  Native ? Native.speak(text, language) : false;

export const stopSpeaking = () => Native?.stopSpeaking();

export const securityStatus = async () =>
  Native
    ? Native.securityStatus()
    : {available: false, reason: 'Security module missing.', hasKey: false};

export const getPublicKey = async () => {
  if (!Native) {
    throw new Error('Security module missing.');
  }
  return Native.getPublicKey();
};

/** Show the fingerprint / face / PIN prompt and sign this confirmation. */
export const signConfirmation = async (actionId: string, summary: string) => {
  if (!Native) {
    throw new Error('Security module missing.');
  }
  return Native.signWithAuth(
    `payguard-confirm:${actionId}`,
    'Confirm with PayGuard',
    summary,
  );
};

/** Ask for fingerprint / PIN before showing private information. */
export const unlock = async (reason: string) => {
  if (!Native) {
    return false;
  }
  try {
    await Native.signWithAuth(`payguard-unlock:${Date.now()}`, 'Unlock PayGuard', reason);
    return true;
  } catch {
    return false;
  }
};
