import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  AccessibilityInfo,
  PermissionsAndroid,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import {
  addEventListener,
  destroy,
  setRecognitionLanguage,
  startListening,
  stopListening,
} from '@ascendtis/react-native-voice-to-text';

import {api, AssistantReply, PendingAction} from '../api';
import ConfirmBox from '../components/ConfirmBox';
import {playSound, speak, stopSpeaking} from '../native';
import {confirmWithSecurity, Session, t} from '../session';
import {colors, ui} from '../theme';

type Line = {from: 'you' | 'payguard'; text: string};

// Saying one of these in live mode ends the conversation.
const STOP_WORDS = ['stop', 'stop listening', 'exit', 'bye', 'நிறுத்து', 'போதும்'];

const requestMicrophone = async () => {
  if (Platform.OS !== 'android') {
    return true;
  }
  const result = await PermissionsAndroid.request(
    PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
    {
      title: 'Microphone',
      message: 'PayGuard needs the microphone so you can talk to it.',
      buttonPositive: 'Allow',
    },
  );
  return result === PermissionsAndroid.RESULTS.GRANTED;
};

const AssistantScreen = ({session}: {session: Session}) => {
  const {account, tamil} = session;
  const [log, setLog] = useState<Line[]>([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [live, setLive] = useState(false);
  const [voiceNote, setVoiceNote] = useState('');

  const liveRef = useRef(false);
  const busyRef = useRef(false);
  const errorsInRow = useRef(0);
  const scrollRef = useRef<React.ComponentRef<typeof ScrollView>>(null);
  const sendRef = useRef<(text: string) => void>(() => {});

  const language = tamil ? 'ta' : 'en';

  const add = (line: Line) => setLog(current => [...current, line].slice(-30));

  const listen = useCallback(async () => {
    try {
      await setRecognitionLanguage(tamil ? 'ta-IN' : 'en-US');
      await startListening();
    } catch (error) {
      setListening(false);
      setVoiceNote(error instanceof Error ? error.message : 'The microphone could not start.');
    }
  }, [tamil]);

  /** Say the reply out loud. With TalkBack on, TalkBack reads it instead. */
  const sayOut = useCallback(
    async (text: string) => {
      if (await AccessibilityInfo.isScreenReaderEnabled()) {
        AccessibilityInfo.announceForAccessibility(text);
        // Give TalkBack time to finish before the microphone opens again.
        await new Promise<void>(resolve => setTimeout(resolve, Math.min(15000, 1500 + text.length * 65)));
        return;
      }
      await speak(text, language);
    },
    [language],
  );

  const endLive = useCallback(() => {
    liveRef.current = false;
    setLive(false);
    stopSpeaking();
    stopListening().catch(() => {});
    setListening(false);
    playSound('stopped');
  }, []);

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || !account || busyRef.current) {
        return;
      }

      if (liveRef.current && STOP_WORDS.includes(message.toLowerCase())) {
        endLive();
        add({from: 'payguard', text: t(tamil, 'Okay, live conversation ended.', 'சரி, நேரடி உரையாடல் முடிந்தது.')});
        return;
      }

      busyRef.current = true;
      setBusy(true);
      setInput('');
      add({from: 'you', text: message});

      let reply: AssistantReply | null = null;
      try {
        reply = await api<AssistantReply>('/api/chat', account.token, {body: {message}});
        add({from: 'payguard', text: reply.reply});
        setPending(reply.pending_action);
        playSound(reply.pending_action ? 'confirm_needed' : reply.event);
      } catch (error) {
        add({from: 'payguard', text: session.handleError(error)});
        playSound('failed');
      } finally {
        busyRef.current = false;
        setBusy(false);
      }

      if (liveRef.current && reply) {
        await sayOut(reply.reply);
        // Money needs the fingerprint / PIN: stop listening until it is done.
        if (reply.pending_action) {
          return;
        }
        if (liveRef.current) {
          playSound('listening');
          listen();
        }
      }
    },
    [account, tamil, session, sayOut, listen, endLive],
  );

  sendRef.current = send;

  useEffect(() => {
    const subs = [
      addEventListener('onSpeechStart', () => {
        setListening(true);
        setVoiceNote('');
      }),
      addEventListener('onSpeechEnd', () => setListening(false)),
      addEventListener('onSpeechPartialResults', event => {
        if (event.value) {
          setInput(event.value);
        }
      }),
      addEventListener('onSpeechResults', event => {
        errorsInRow.current = 0;
        const text = event.value ?? '';
        if (liveRef.current) {
          sendRef.current(text); // live mode: send by itself
        } else {
          setInput(text); // tap-to-talk: check it, then tap Send
        }
      }),
      addEventListener('onSpeechError', event => {
        setListening(false);
        if (liveRef.current && errorsInRow.current < 3) {
          // Silence or a missed word: keep the conversation going.
          errorsInRow.current += 1;
          setTimeout(() => liveRef.current && listen(), 600);
          return;
        }
        if (liveRef.current) {
          endLive();
        }
        setVoiceNote(event.message || 'I could not hear you.');
      }),
    ];

    return () => {
      subs.forEach(sub => sub.remove());
      liveRef.current = false;
      stopSpeaking();
      destroy().catch(() => {});
    };
  }, [listen, endLive]);

  const tapToTalk = async () => {
    if (listening) {
      await stopListening().catch(() => {});
      return;
    }
    if (!(await requestMicrophone())) {
      setVoiceNote('Please allow the microphone to talk to PayGuard.');
      return;
    }
    playSound('listening');
    listen();
  };

  const toggleLive = async () => {
    if (live) {
      endLive();
      return;
    }
    if (!(await requestMicrophone())) {
      setVoiceNote('Please allow the microphone to talk to PayGuard.');
      return;
    }
    liveRef.current = true;
    errorsInRow.current = 0;
    setLive(true);
    const hello = t(
      tamil,
      'Live conversation on. What would you like to do?',
      'நேரடி உரையாடல் தொடங்கியது. என்ன செய்ய வேண்டும்?',
    );
    add({from: 'payguard', text: hello});
    await sayOut(hello);
    if (liveRef.current) {
      playSound('listening');
      listen();
    }
  };

  const confirm = async () => {
    if (!pending || !account) {
      return;
    }
    const action = pending;
    setBusy(true);
    try {
      const reply = await confirmWithSecurity(account.token, action);
      setPending(reply.pending_action);
      add({from: 'payguard', text: reply.reply});
      if (liveRef.current) {
        await sayOut(reply.reply);
        if (liveRef.current) {
          playSound('listening');
          listen();
        }
      }
    } catch (error) {
      // Cancelled prompt: the payment is still waiting; nothing was sent.
      const text = error instanceof Error && error.message ? error.message : 'Not confirmed.';
      add({from: 'payguard', text: `${text} Nothing was sent.`});
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!account) {
      return;
    }
    setPending(null);
    try {
      const reply = await api<AssistantReply>('/api/chat/cancel', account.token, {body: {}});
      add({from: 'payguard', text: reply.reply});
    } catch (error) {
      add({from: 'payguard', text: session.handleError(error)});
    }
  };

  if (!account) {
    return (
      <View style={styles.screen}>
        <View style={[ui.card, styles.margin]}>
          <Text style={ui.body}>{t(tamil, 'Please log in on the Home tab first.', 'முதலில் முகப்பில் உள்நுழையுங்கள்.')}</Text>
        </View>
      </View>
    );
  }

  const examples = account.isOwner
    ? t(tamil, '"Send $20 to Priya", "Did any payment fail?", "Show refund requests"', '"பிரியாவுக்கு 20 டாலர் அனுப்பு", "ஏதாவது கட்டணம் தோல்வியா?"')
    : t(tamil, '"Show my purchases", "My latest order arrived damaged"', '"என் வாங்குதல்களைக் காட்டு", "என் கடைசி ஆர்டர் உடைந்து வந்தது"');

  return (
    <View style={styles.screen}>
      <ScrollView
        ref={scrollRef}
        style={styles.log}
        contentContainerStyle={styles.logContent}
        onContentSizeChange={() => scrollRef.current?.scrollToEnd({animated: true})}>
        {log.length === 0 && (
          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Talk or type', 'பேசுங்கள் அல்லது தட்டச்சு செய்யுங்கள்')}
            </Text>
            <Text style={ui.muted}>{t(tamil, 'Try', 'உதாரணம்')}: {examples}</Text>
          </View>
        )}
        {log.map((line, index) => (
          <View
            key={index}
            accessible
            accessibilityLiveRegion={index === log.length - 1 && line.from === 'payguard' ? 'polite' : 'none'}
            style={[styles.bubble, line.from === 'you' ? styles.you : styles.payguard]}>
            <Text style={styles.from}>{line.from === 'you' ? t(tamil, 'You', 'நீங்கள்') : 'PayGuard'}</Text>
            <Text style={styles.text}>{line.text}</Text>
          </View>
        ))}
        {pending && <ConfirmBox action={pending} busy={busy} onConfirm={confirm} onCancel={cancel} />}
      </ScrollView>

      <View style={styles.bottom}>
        {voiceNote ? (
          <Text style={styles.voiceNote} accessibilityLiveRegion="polite">
            {voiceNote}
          </Text>
        ) : null}
        {live && (
          <Text style={styles.liveNote} accessibilityLiveRegion="polite">
            {listening
              ? t(tamil, '🔴 Listening... say "stop" to end', '🔴 கேட்கிறேன்... முடிக்க "நிறுத்து" சொல்லுங்கள்')
              : t(tamil, 'Live conversation on', 'நேரடி உரையாடல் இயக்கத்தில்')}
          </Text>
        )}
        <View style={styles.inputRow}>
          <TextInput
            value={input}
            onChangeText={setInput}
            onSubmitEditing={() => send(input)}
            accessibilityLabel={t(tamil, 'Your request', 'உங்கள் கோரிக்கை')}
            placeholder={t(tamil, 'Type a request', 'கோரிக்கையைத் தட்டச்சு செய்யுங்கள்')}
            placeholderTextColor="#6B7280"
            returnKeyType="send"
            maxLength={300}
            style={[ui.input, styles.input]}
          />
          <TouchableOpacity
            onPress={() => send(input)}
            disabled={busy || !input.trim()}
            accessibilityRole="button"
            accessibilityLabel={t(tamil, 'Send message', 'செய்தியை அனுப்பு')}
            accessibilityState={{disabled: busy || !input.trim(), busy}}
            style={[styles.sendButton, (busy || !input.trim()) && ui.disabled]}>
            <Text style={styles.sendText}>➤</Text>
          </TouchableOpacity>
        </View>
        <View style={styles.voiceRow}>
          <TouchableOpacity
            onPress={tapToTalk}
            disabled={live}
            accessibilityRole="button"
            accessibilityLabel={
              listening && !live
                ? t(tamil, 'Stop listening', 'கேட்பதை நிறுத்து')
                : t(tamil, 'Tap to talk once', 'ஒருமுறை பேச தட்டவும்')
            }
            accessibilityState={{disabled: live}}
            style={[styles.voiceButton, styles.micButton, live && ui.disabled]}>
            <Text style={styles.voiceText}>
              {listening && !live ? '⏹ ' : '🎙️ '}
              {listening && !live ? t(tamil, 'Stop', 'நிறுத்து') : t(tamil, 'Talk', 'பேசு')}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={toggleLive}
            accessibilityRole="switch"
            accessibilityLabel={t(tamil, 'Live conversation', 'நேரடி உரையாடல்')}
            accessibilityState={{checked: live}}
            style={[styles.voiceButton, live ? styles.liveOn : styles.liveOff]}>
            <Text style={styles.voiceText}>
              {live ? t(tamil, '● Live: ON', '● நேரடி: ஆன்') : t(tamil, '○ Live conversation', '○ நேரடி உரையாடல்')}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  margin: {
    margin: 16,
  },
  log: {
    flex: 1,
  },
  logContent: {
    padding: 16,
  },
  bubble: {
    borderRadius: 14,
    padding: 12,
    marginBottom: 10,
  },
  you: {
    backgroundColor: '#E8F0FE',
    marginLeft: 40,
  },
  payguard: {
    backgroundColor: colors.card,
    marginRight: 40,
  },
  from: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: '700',
    marginBottom: 3,
  },
  text: {
    color: colors.ink,
    fontSize: 17,
    lineHeight: 24,
  },
  bottom: {
    backgroundColor: colors.card,
    borderTopWidth: 1,
    borderTopColor: '#DCE3EE',
    padding: 12,
  },
  voiceNote: {
    color: colors.bad,
    fontSize: 14,
    marginBottom: 6,
  },
  liveNote: {
    color: colors.good,
    fontSize: 15,
    fontWeight: '700',
    marginBottom: 6,
  },
  inputRow: {
    flexDirection: 'row',
    gap: 8,
  },
  input: {
    flex: 1,
  },
  sendButton: {
    width: 54,
    borderRadius: 12,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendText: {
    color: '#FFFFFF',
    fontSize: 22,
  },
  voiceRow: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 8,
  },
  voiceButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  micButton: {
    backgroundColor: colors.brandBlue,
  },
  liveOff: {
    backgroundColor: '#475569',
  },
  liveOn: {
    backgroundColor: colors.good,
  },
  voiceText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '800',
  },
});

export default AssistantScreen;
