import {NativeEventEmitter, NativeModules} from 'react-native';

import {BACKEND_URL} from './api';

// LiveVoiceModule.kt: microphone <-> PayGuard server <-> Gemini Live.
const Live = NativeModules.PayGuardLive as
  | {
      start(url: string, token: string): void;
      stop(): void;
      setMuted(value: boolean): void;
      say(text: string): void;
    }
  | undefined;

export type LiveEvent = {
  type:
    | 'ready'
    | 'listening'
    | 'you'
    | 'payguard'
    | 'action'
    | 'interrupted'
    | 'turn_complete'
    | 'end'
    | 'closed';
  text?: string;
  message?: string;
  reply?: string;
  pending_action?: any;
  event?: string | null;
};

export const liveAvailable = () => Boolean(Live);

export const startLive = (token: string, onEvent: (event: LiveEvent) => void) => {
  if (!Live) {
    throw new Error('Live voice is not available in this app version.');
  }
  const emitter = new NativeEventEmitter(NativeModules.PayGuardLive);
  const sub = emitter.addListener('PayGuardLive', (json: unknown) => {
    try {
      onEvent(JSON.parse(String(json)));
    } catch {
      // ignore anything that is not our JSON
    }
  });
  Live.start(`${BACKEND_URL.replace(/^http/, 'ws')}/api/live`, token);
  return () => {
    sub.remove();
    Live.stop();
  };
};

export const muteLive = (value: boolean) => Live?.setMuted(value);
export const liveSay = (text: string) => Live?.say(text);
