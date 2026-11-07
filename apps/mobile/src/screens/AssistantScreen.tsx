import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  AccessibilityInfo,
  AppState,
  Linking,
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
import {WebProduct, WebProductRow} from '../components/BestProducts';
import {LiveEvent, liveSay, muteLive, startLive} from '../live';
import {playSound} from '../native';
import {confirmWithSecurity, Session, t} from '../session';
import {colors, ui} from '../theme';

// products: store links for 'find the best ...' answers.
type Line = {from: 'you' | 'payguard'; text: string; products?: WebProduct[]};

const webProducts = (rows?: any[]): WebProduct[] | undefined => {
  const found = (rows ?? []).filter(r => r && r.type === 'web_product' && r.link);
  return found.length ? found : undefined;
};

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

  const busyRef = useRef(false);
  const stopLiveRef = useRef<(() => void) | null>(null);
  // Live turn being built: each new turn starts a new pair of lines.
  const turnOpen = useRef({you: false, payguard: false});
  const scrollRef = useRef<React.ComponentRef<typeof ScrollView>>(null);

  const add = (line: Line) => setLog(current => [...current, line].slice(-40));

  /** Update the last line of this speaker in the current live turn, or add one. */
  const liveLine = (from: Line['from'], text: string, append: boolean) =>
    setLog(current => {
      const lines = [...current];
      if (turnOpen.current[from]) {
        for (let i = lines.length - 1; i >= 0; i--) {
          if (lines[i].from === from) {
            lines[i] = {from, text: append ? lines[i].text + text : text};
            return lines;
          }
        }
      }
      turnOpen.current[from] = true;
      return [...lines, {from, text}].slice(-40);
    });

  // ---------- typed / tap-to-talk chat ----------

  const send = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || !account || busyRef.current) {
        return;
      }
      busyRef.current = true;
      setBusy(true);
      setInput('');
      add({from: 'you', text: message});
      try {
        const reply = await api<AssistantReply>('/api/chat', account.token, {body: {message}});
        add({from: 'payguard', text: reply.reply, products: webProducts(reply.transactions)});
        setPending(reply.pending_action);
        playSound(
          reply.pending_action?.warnings?.length
            ? 'warning' // low notes: scam warning signs
            : reply.pending_action
              ? 'confirm_needed'
              : reply.event,
        );
      } catch (error) {
        add({from: 'payguard', text: session.handleError(error)});
        playSound('failed');
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [account, session],
  );

  useEffect(() => {
    const subs = [
      addEventListener('onSpeechStart', () => {
        setListening(true);
        setVoiceNote('');
      }),
      addEventListener('onSpeechEnd', () => setListening(false)),
      addEventListener('onSpeechPartialResults', event => event.value && setInput(event.value)),
      // Tap-to-talk: put the words in the box; the person checks them and taps Send.
      addEventListener('onSpeechResults', event => setInput(event.value ?? '')),
      addEventListener('onSpeechError', event => {
        setListening(false);
        setVoiceNote(event.message || 'I could not hear you.');
      }),
    ];
    return () => {
      subs.forEach(sub => sub.remove());
      destroy().catch(() => {});
    };
  }, []);

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
    try {
      await setRecognitionLanguage(tamil ? 'ta-IN' : 'en-US');
      await startListening();
    } catch (error) {
      setVoiceNote(error instanceof Error ? error.message : 'The microphone could not start.');
    }
  };

  // ---------- Gemini Live: a real two-way voice conversation ----------

  const endLive = useCallback((note?: string) => {
    stopLiveRef.current?.();
    stopLiveRef.current = null;
    setLive(false);
    playSound('stopped');
    AccessibilityInfo.announceForAccessibility(note || 'Live conversation off.');
    if (note) {
      setVoiceNote(note);
    }
  }, []);

  const onLiveEvent = useCallback(
    (event: LiveEvent) => {
      switch (event.type) {
        case 'listening':
          playSound('listening');
          AccessibilityInfo.announceForAccessibility('Live conversation on. Speak now.');
          break;
        case 'you':
          liveLine('you', event.text ?? '', false);
          break;
        case 'payguard':
          liveLine('payguard', event.text ?? '', true);
          break;
        case 'action':
          if (webProducts(event.transactions)) {
            add({from: 'payguard', text: 'Store links / கடை இணைப்புகள்:', products: webProducts(event.transactions)});
          }
          if (event.pending_action) {
            // Money waits for the fingerprint / PayPal: stop listening until then.
            muteLive(true);
            setPending(event.pending_action);
            playSound(event.pending_action.warnings?.length ? 'warning' : 'confirm_needed');
          } else if (event.event) {
            playSound(event.event);
          }
          break;
        case 'turn_complete':
          turnOpen.current = {you: false, payguard: false};
          break;
        case 'end':
          endLive(event.message);
          break;
        case 'closed':
          if (stopLiveRef.current) {
            endLive();
          }
          break;
      }
    },
    [endLive],
  );

  const toggleLive = async () => {
    if (live) {
      endLive();
      return;
    }
    if (!account) {
      return;
    }
    if (!(await requestMicrophone())) {
      setVoiceNote('Please allow the microphone to talk to PayGuard.');
      return;
    }
    setVoiceNote('');
    turnOpen.current = {you: false, payguard: false};
    try {
      stopLiveRef.current = startLive(account.token, onLiveEvent);
      setLive(true);
    } catch (error) {
      setVoiceNote(error instanceof Error ? error.message : 'Live voice could not start.');
    }
  };

  // Privacy: never leave the microphone open in the background.
  useEffect(() => {
    const sub = AppState.addEventListener('change', state => {
      if (state !== 'active' && stopLiveRef.current) {
        endLive();
      }
    });
    return () => {
      sub.remove();
      stopLiveRef.current?.();
    };
  }, [endLive]);

  // ---------- confirm / cancel (both modes) ----------

  const confirm = async (pin: string) => {
    if (!pending || !account) {
      return;
    }
    const action = pending;
    // A shop order is paid in PayPal's own checkout page.
    if (action.type === 'checkout' && action.url) {
      setPending(null);
      muteLive(false);
      playSound('request_sent');
      await Linking.openURL(action.url);
      return;
    }
    setBusy(true);
    try {
      const reply = await confirmWithSecurity(account.token, action, pin);
      setPending(reply.pending_action);
      add({from: 'payguard', text: reply.reply});
      if (live && !reply.pending_action) {
        liveSay(reply.reply); // PayGuard says the result out loud
        muteLive(false);
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
      if (live) {
        liveSay(reply.reply);
      }
    } catch (error) {
      add({from: 'payguard', text: session.handleError(error)});
    } finally {
      muteLive(false);
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
    ? t(tamil, '"Search headphones", "Send $20 to Priya", "Did any payment fail?"', '"ஹெட்போன் தேடு", "பிரியாவுக்கு 20 டாலர் அனுப்பு", "ஏதாவது கட்டணம் தோல்வியா?"')
    : t(tamil, '"Search headphones", "Tell me about number 2", "Show my cart", "My latest order arrived damaged"', '"ஹெட்போன் தேடு", "என் கூடையைக் காட்டு", "என் கடைசி ஆர்டர் உடைந்து வந்தது"');

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
            accessibilityLiveRegion={!live && index === log.length - 1 && line.from === 'payguard' ? 'polite' : 'none'}
            style={[styles.bubble, line.from === 'you' ? styles.you : styles.payguard]}>
            <Text style={styles.from}>{line.from === 'you' ? t(tamil, 'You', 'நீங்கள்') : 'PayGuard'}</Text>
            <Text style={styles.text}>{line.text}</Text>
          </View>
        ))}
        {/* Store links sit outside the bubbles so each one is its own button. */}
        {log.length > 0 && log[log.length - 1].products?.map(item => (
          <WebProductRow key={`${item.rank}-${item.link}`} item={item} tamil={tamil} />
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
            {pending
              ? t(tamil, '⏸ Paused: confirm on screen', '⏸ நிறுத்தம்: திரையில் உறுதிப்படுத்துங்கள்')
              : t(tamil, 'Live with Gemini: just talk. Tap again to end.', 'Gemini உடன் நேரடி: பேசுங்கள். முடிக்க மீண்டும் தட்டவும்.')}
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
              {live ? t(tamil, 'End live conversation', 'நேரடி உரையாடலை முடி') : t(tamil, 'Live conversation', 'நேரடி உரையாடல்')}
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
    backgroundColor: colors.brandSoft,
    marginLeft: 40,
  },
  payguard: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.line,
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
    minHeight: 52,
    justifyContent: 'center',
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  micButton: {
    backgroundColor: colors.ink,
  },
  liveOff: {
    backgroundColor: colors.brand,
  },
  liveOn: {
    backgroundColor: colors.bad,
  },
  voiceText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '800',
  },
});

export default AssistantScreen;
